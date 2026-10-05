"""Автоматическая email-рассылка компаниям из карт (без сайта) и из анализа сайтов (сайт с проблемами).

Письма уходят через вашу почту (SMTP), не чаще daily_limit в день, с паузами, только в рабочие часы.
Каждому адресу и каждой компании пишем один раз. Ответы проверяются через IMAP:
ответившие больше не получают писем, отказы («не пишите», «отпишите») попадают в stoplist.txt,
о каждом ответе приходит уведомление в Telegram-бота.
"""
import csv
import email
import email.policy
import imaplib
import random
import re
import smtplib
import sqlite3
import ssl
import time
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from urllib.parse import urlparse

import notify
from common import BASE, DATA, find_emails

TEMPLATES = BASE / "templates"
STOPLIST = BASE / "stoplist.txt"
DB = DATA / "outreach.db"
LOG = DATA / "outreach.csv"

FREE_MAIL = {"gmail.com", "yandex.ru", "ya.ru", "yandex.com", "mail.ru", "bk.ru", "inbox.ru", "list.ru",
             "internet.ru", "rambler.ru", "icloud.com", "outlook.com", "hotmail.com", "yahoo.com", "me.com"}
STOP_REPLY = re.compile(r"отпиш|не пиш|не присыл|не беспоко|удалите|не интерес|неинтерес|не актуал|"
                        r"неактуал|не нужн|unsubscribe|спам", re.I)

PROBLEM_TEXT = [
    (r"нет HTTPS", "сайт открывается без защищённого соединения (HTTPS) — браузеры помечают его как «Не защищено»"),
    (r"не адаптирован", "сайт не адаптирован под телефоны, а с них сейчас приходит большая часть посетителей"),
    (r"копирайт (\d{4})", "в подвале сайта указан {0} год — посетителям может показаться, что сайт заброшен"),
    (r"медленный \(([\d.,]+)", "главная страница загружается {0} с — часть посетителей уходит, не дождавшись"),
    (r"старые технологии", "сайт сделан на устаревших технологиях, его сложно развивать и поддерживать"),
    (r"нет title|нет meta description", "у страниц нет заголовка или описания для поисковиков — сайт хуже находится в Яндексе и Google"),
]


# ---------------- база отправленных ----------------
def _db():
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS sent (
        email TEXT PRIMARY KEY, key TEXT, company TEXT, kind TEXT, subject TEXT, status TEXT, at TEXT)""")
    db.execute("CREATE INDEX IF NOT EXISTS sent_key ON sent(key)")
    return db


def _log(row):
    new = not LOG.exists()
    with open(LOG, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["at", "status", "email", "company", "kind", "subject"])
        w.writerow(row)


def stats():
    db = _db()
    today = datetime.now().strftime("%Y-%m-%d")
    res = {
        "today": db.execute("SELECT COUNT(*) FROM sent WHERE status!='bad' AND at LIKE ?", (today + "%",)).fetchone()[0],
        "total": db.execute("SELECT COUNT(*) FROM sent WHERE status!='bad'").fetchone()[0],
    }
    for st in ("replied", "stop", "bounce", "bad"):
        res[st] = db.execute("SELECT COUNT(*) FROM sent WHERE status=?", (st,)).fetchone()[0]
    db.close()
    return res


# ---------------- стоп-лист ----------------
def load_stoplist():
    if not STOPLIST.exists():
        return set()
    return {l.strip().lower() for l in STOPLIST.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def add_to_stoplist(addr):
    s = load_stoplist()
    if addr.lower() not in s:
        with open(STOPLIST, "a", encoding="utf-8") as f:
            f.write(addr.lower() + "\n")


def _blocked(addr, site_domain, stop):
    dom = addr.split("@")[-1]
    return addr in stop or dom in stop or (site_domain and site_domain in stop)


# ---------------- очередь ----------------
def domain(url):
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    d = urlparse(url).netloc.lower().split(":")[0]
    return d[4:] if d.startswith("www.") else d


def _read(name):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _first_email(s):
    found = find_emails(s or "")
    return found[0] if found else ""


def build_queue(cfg):
    """Список писем к отправке: сначала компании без сайта, потом сайты с наибольшим числом проблем."""
    o = cfg["outreach"]
    srcs = o.get("sources") or ["maps", "sites"]
    maps = _read("maps")
    by_domain = {domain(r["website"]): r for r in maps if r.get("website")}
    stop = load_stoplist()
    db = _db()
    sent_emails = {r[0] for r in db.execute("SELECT email FROM sent")}
    sent_keys = {r[0] for r in db.execute("SELECT key FROM sent")}
    db.close()

    out, seen = [], set()

    def push(item):
        e, k = item["email"], item["key"]
        if not e or e in sent_emails or k in sent_keys or e in seen or k in seen:
            return
        if _blocked(e, item.get("site_domain"), stop):
            return
        seen.update((e, k))
        out.append(item)

    if "maps" in srcs:
        for r in maps:
            if r.get("website"):
                continue  # компании с сайтом пойдут через анализ сайтов
            e = _first_email(r.get("email"))
            dom = e.split("@")[-1]
            key = dom if dom and dom not in FREE_MAIL else f"{r.get('company', '').lower()}|{r.get('city', '').lower()}"
            push({"kind": "no_site", "email": e, "key": key, "company": r.get("company", ""),
                  "city": r.get("city", ""), "niche": r.get("title", ""), "website": "", "problems": ""})

    if "sites" in srcs:
        rows = []
        for r in _read("sites"):
            try:
                score = int(r.get("score") or 0)
            except ValueError:
                score = 0
            if score >= int(o.get("min_problems", 2)):
                rows.append((score, r))
        for score, r in sorted(rows, key=lambda x: -x[0]):
            d = domain(r.get("website") or r.get("url"))
            m = by_domain.get(d, {})
            push({"kind": "site_problems", "email": _first_email(r.get("email")), "key": d, "site_domain": d,
                  "company": m.get("company") or r.get("title") or d, "city": m.get("city", ""),
                  "niche": m.get("title", ""), "website": d, "problems": r.get("notes", "")})
    return out


# ---------------- письмо ----------------
class _Safe(dict):
    def __missing__(self, k):
        return ""


def problems_text(notes):
    lines = []
    for pat, text in PROBLEM_TEXT:
        m = re.search(pat, notes or "")
        if m and text not in lines:
            lines.append(text.format(*[g.replace(",", ".") for g in m.groups()]))
    return "\n".join(f"— {l}" for l in lines)


def load_template(kind):
    p = TEMPLATES / f"{kind}.txt"
    raw = p.read_text(encoding="utf-8").strip()
    first, _, body = raw.partition("\n")
    if not first.lower().startswith("тема:"):
        raise RuntimeError(f"{p}: первая строка должна начинаться с «Тема:»")
    return first.split(":", 1)[1].strip(), body.strip()


def render(cfg, item):
    o = cfg["outreach"]
    subj, body = load_template(item["kind"])
    v = _Safe(item)
    v["problems"] = problems_text(item.get("problems"))
    v["signature"] = (o.get("signature") or "").strip()
    v["from_name"] = o.get("from_name", "")
    subj = subj.format_map(v).replace("«»", "").strip()
    body = re.sub(r"\n{3,}", "\n\n", body.format_map(v))
    return subj, body


def make_message(cfg, to, subject, body):
    o = cfg["outreach"]
    sender = o["smtp_user"]
    msg = EmailMessage()
    msg["From"] = formataddr((o.get("from_name") or "", sender))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    reply = o.get("reply_to") or sender
    if reply != sender:
        msg["Reply-To"] = reply
    msg["List-Unsubscribe"] = f"<mailto:{reply}?subject=unsubscribe>"
    msg.set_content(body)
    return msg


def _smtp(cfg):
    o = cfg["outreach"]
    host, port = o["smtp_host"], int(o.get("smtp_port", 465))
    ctx = ssl.create_default_context()
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
    else:
        s = smtplib.SMTP(host, port, timeout=30)
        s.starttls(context=ctx)
    s.login(o["smtp_user"], o["smtp_password"])
    return s


def explain(e, cfg):
    """Понятное объяснение ошибки почты."""
    host = cfg["outreach"].get("smtp_host", "")
    if isinstance(e, (smtplib.SMTPAuthenticationError, smtplib.SMTPServerDisconnected)):
        tip = "Почта не приняла вход. Нужен ПАРОЛЬ ПРИЛОЖЕНИЯ, а не обычный пароль от почты."
        if "gmail" in host:
            tip += ("\nGmail: включите двухэтапную проверку, затем создайте пароль на "
                    "myaccount.google.com/apppasswords — это 16 латинских букв.")
        elif "yandex" in host:
            tip += ("\nЯндекс: id.yandex.ru → Безопасность → Пароли приложений → Почта; "
                    "и в настройках почты включите «Почтовые программы» (IMAP).")
        elif "mail.ru" in host:
            tip += "\nMail.ru: Настройки → Безопасность → Пароли для внешних приложений."
        return f"{tip}\n({type(e).__name__}: {e})"
    return f"{type(e).__name__}: {e}"


def check_ready(cfg):
    """Пустая строка, если всё настроено, иначе — что не так."""
    o = cfg.get("outreach") or {}
    if not (o.get("smtp_host") and o.get("smtp_user") and o.get("smtp_password")):
        return "почта не настроена (Рассылка → 5 Почта и подпись)"
    if not o.get("from_name") or not (o.get("signature") or "").strip():
        return "не заполнены имя отправителя и подпись"
    for k in ("no_site", "site_problems"):
        if not (TEMPLATES / f"{k}.txt").exists():
            return f"нет шаблона templates/{k}.txt"
    return ""


def in_window(cfg, now=None):
    o = cfg["outreach"]
    now = now or datetime.now()
    if o.get("weekdays_only", True) and now.weekday() >= 5:
        return False
    return int(o.get("hour_from", 10)) <= now.hour < int(o.get("hour_to", 18))


# ---------------- отправка ----------------
def run(cfg, dry_run=False, force=False, limit=None):
    """dry_run — только показать письма; force — отправить вне расписания и даже если рассылка выключена."""
    o = cfg["outreach"]
    if not dry_run:
        if not o.get("enabled") and not force:
            print("[outreach] автоотправка выключена (outreach.enabled: false)")
            return
        problem = check_ready(cfg)
        if problem:
            raise RuntimeError(f"[outreach] {problem}")
        if not force and not in_window(cfg):
            print("[outreach] сейчас нерабочее время по расписанию — пропускаю")
            return

    left = int(o.get("daily_limit", 30)) - stats()["today"]
    if limit is not None:
        left = min(left, limit)
    queue = build_queue(cfg)
    print(f"[outreach] в очереди: {len(queue)}, можно отправить сегодня: {max(left, 0)}")
    if left <= 0 or not queue:
        return
    batch = queue[:left]

    if dry_run:
        for it in batch:
            subj, body = render(cfg, it)
            print(f"\n=== {it['email']}  ({it['company']}) ===\nТема: {subj}\n\n{body}\n")
        return

    db = _db()
    sent, errors = 0, 0
    try:
        for i, it in enumerate(batch):
            if not force and not in_window(cfg):
                print("  рабочее время закончилось — остальное завтра")
                break
            subj, body = render(cfg, it)
            now = datetime.now().isoformat(timespec="seconds")
            try:
                s = _smtp(cfg)
                try:
                    s.send_message(make_message(cfg, it["email"], subj, body))
                finally:
                    s.quit()
                status = "sent"
                sent += 1
                errors = 0
                print(f"  ✔ {it['email']}  {it['company']}")
            except smtplib.SMTPAuthenticationError as e:
                notify.send(cfg, f"✖ Рассылка остановлена: почта не принимает логин/пароль.\n{e}")
                raise RuntimeError(f"ошибка входа в почту: {e}")
            except smtplib.SMTPRecipientsRefused:
                status = "bad"
                print(f"  ✖ адрес не принят: {it['email']}")
            except Exception as e:
                errors += 1
                print(f"  ! {it['email']}: {type(e).__name__}: {str(e)[:150]}")
                if errors >= 3:
                    notify.send(cfg, f"⚠ Рассылка остановлена после 3 ошибок подряд: {type(e).__name__}: {str(e)[:300]}")
                    break
                continue
            db.execute("INSERT OR REPLACE INTO sent VALUES (?,?,?,?,?,?,?)",
                       (it["email"], it["key"], it["company"], it["kind"], subj, status, now))
            db.commit()
            _log([now, status, it["email"], it["company"], it["kind"], subj])
            if i < len(batch) - 1:
                time.sleep(random.uniform(int(o.get("delay_min_sec", 90)), int(o.get("delay_max_sec", 240))))
    finally:
        db.close()
    print(f"  -> отправлено писем: {sent}")
    if sent:
        st = stats()
        notify.send(cfg, f"📨 Рассылка: отправлено {sent} (сегодня {st['today']}/{o.get('daily_limit', 30)}), "
                         f"в очереди ещё {max(len(queue) - sent, 0)}")


def send_test(cfg):
    """Тестовое письмо себе — первым письмом из очереди или примером."""
    o = cfg["outreach"]
    queue = build_queue(cfg)
    item = queue[0] if queue else {"kind": "site_problems", "company": "Пример", "city": "Москва", "niche": "кафе",
                                   "website": "example-cafe.ru", "problems": "нет HTTPS; не адаптирован под мобильные; копирайт 2019 г."}
    subj, body = render(cfg, item)
    s = _smtp(cfg)
    try:
        s.send_message(make_message(cfg, o["smtp_user"], "[ТЕСТ] " + subj, body))
    finally:
        s.quit()
    return o["smtp_user"]


# ---------------- ответы (IMAP) ----------------
def _dec(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _text(msg):
    parts = list(msg.walk()) if msg.is_multipart() else [msg]
    for p in parts:
        if p.get_content_type() == "text/plain" and not p.get_filename():
            try:
                return p.get_content()
            except Exception:
                return (p.get_payload(decode=True) or b"").decode("utf-8", "replace")
    for p in parts:
        if p.get_content_type() == "text/html":
            return re.sub(r"<[^>]+>", " ", (p.get_payload(decode=True) or b"").decode("utf-8", "replace"))
    return ""


def check_replies(cfg, days=7):
    """Ищет во входящих ответы и возвраты на наши письма. Не помечает письма прочитанными."""
    o = cfg["outreach"]
    if not (o.get("smtp_user") and o.get("smtp_password")):
        return
    host = o.get("imap_host") or o["smtp_host"].replace("smtp.", "imap.", 1)
    db = _db()
    waiting = {r[0]: r[1] for r in db.execute("SELECT email, company FROM sent WHERE status='sent'")}
    if not waiting:
        db.close()
        return
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    found = 0
    M = imaplib.IMAP4_SSL(host, 993, ssl_context=ssl.create_default_context())
    try:
        M.login(o["smtp_user"], o["smtp_password"])
        M.select("INBOX", readonly=True)
        _, data = M.search(None, "SINCE", since)
        for num in data[0].split():
            _, msgdata = M.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(msgdata[0][1], policy=email.policy.default)
            sender = parseaddr(msg.get("From", ""))[1].lower()
            text = _text(msg)
            if re.match(r"(mailer-daemon|postmaster)@", sender):
                for addr in find_emails(text):
                    if addr in waiting:
                        db.execute("UPDATE sent SET status='bounce' WHERE email=?", (addr,))
                        waiting.pop(addr)
                continue
            if sender not in waiting:
                continue
            body = text.split("\n>")[0]  # без цитаты нашего письма
            body = re.split(r"\n.{0,80}(?:пишет|wrote):", body)[0].strip()
            refused = bool(STOP_REPLY.search(body)) or bool(re.fullmatch(r"\W*нет\W*", body, re.I))
            db.execute("UPDATE sent SET status=? WHERE email=?", ("stop" if refused else "replied", sender))
            if refused:
                add_to_stoplist(sender)
            company = waiting.pop(sender)
            found += 1
            icon = "🙅 Отказ" if refused else "🔥 ОТВЕТ НА РАССЫЛКУ"
            notify.send(cfg, f"{icon}\n{company} <{sender}>\nТема: {_dec(msg.get('Subject'))}\n\n{body[:1500]}")
            print(f"  {'отказ' if refused else 'ответ'}: {sender} ({company})")
        db.commit()
    finally:
        db.close()
        try:
            M.logout()
        except Exception:
            pass
    print(f"[outreach] новых ответов: {found}")
