"""Telegram без входа в аккаунт: читает веб-версию публичных каналов t.me/s/<имя>.

Работает только для публичных каналов (и части публичных чатов) с включённым
веб-просмотром. Ключи API и вход не нужны.
"""
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from common import HEADERS, Store, matches
import notify

BASE_URL = "https://t.me/s/"


def clean_name(name):
    name = name.strip()
    name = re.sub(r"^(https?://)?(t|telegram)\.me/(s/)?", "", name)
    return name.lstrip("@").split("/")[0].split("?")[0]


def fetch_page(name, before=None):
    """Возвращает (title, [посты]) — посты от старых к новым."""
    params = {"before": before} if before else None
    r = requests.get(BASE_URL + name, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = soup.select_one(".tgme_channel_info_header_title") or soup.select_one("meta[property='og:title']")
    title = title_el.get_text(strip=True) if title_el and title_el.name != "meta" else (title_el.get("content", "") if title_el else name)
    posts = []
    for m in soup.select("div.tgme_widget_message[data-post]"):
        text_el = m.select_one(".tgme_widget_message_text")
        if not text_el:
            continue
        for br in text_el.find_all("br"):
            br.replace_with("\n")
        post = m["data-post"]  # "channel/123"
        t = m.select_one("time[datetime]")
        author = m.select_one(".tgme_widget_message_from_author")
        links = [a["href"] for a in text_el.find_all("a", href=True)]
        posts.append({
            "id": int(post.split("/")[-1]),
            "url": "https://t.me/" + post,
            "text": text_el.get_text(),
            "date": t["datetime"][:16].replace("T", " ") if t else "",
            "author": author.get_text(strip=True) if author else "",
            "links": links,
        })
    return title, posts


def has_preview(name):
    """Проверка канала: (ok, title, дата последнего поста | причина)."""
    try:
        title, posts = fetch_page(clean_name(name))
    except Exception as e:
        return False, "", f"ошибка: {str(e)[:60]}"
    if not posts:
        return False, title, "нет веб-просмотра (закрытый чат или неверное имя)"
    return True, title, posts[-1]["date"]


def _contacts(post):
    """Достаём контакт автора объявления: @username или ссылку t.me из текста."""
    found = re.findall(r"@[A-Za-z][A-Za-z0-9_]{4,}", post["text"])
    found += [l for l in post["links"] if re.match(r"https?://t\.me/[A-Za-z]", l) and "/s/" not in l]
    out = []
    for c in found:
        if c not in out:
            out.append(c)
    return ", ".join(out[:3])


def scan(cfg, store=None, quiet=False):
    tg = cfg["telegram"]
    own = store is None
    store = store or Store("telegram")
    limit = int(tg.get("history_limit", 100))
    new_total = 0
    for raw in tg.get("chats") or []:
        name = clean_name(raw)
        if not quiet:
            print(f"[telegram] {name}")
        try:
            title, posts = fetch_page(name)
            seen = len(posts)
            # листаем назад, пока не наберём limit сообщений
            while posts and seen < limit:
                _, older = fetch_page(name, before=posts[0]["id"])
                if not older:
                    break
                posts = older + posts
                seen += len(older)
                time.sleep(1)
        except Exception as e:
            print(f"  ! {name}: {e}")
            continue
        if not posts:
            print(f"  ! {name}: нет веб-просмотра — канал закрытый или имя неверное")
            continue
        for p in posts[-limit:]:
            if not matches(p["text"], cfg):
                continue
            lead = {
                "source": f"Telegram: {title}",
                "title": p["text"].strip().split("\n")[0][:120],
                "company": _contacts(p) or p["author"],
                "url": p["url"],
                "text": p["text"],
                "notes": p["date"],
            }
            if store.add(lead, key=p["url"]):
                new_total += 1
                notify.send(cfg, f"🔔 {lead['source']}\n{lead['company']}\n{p['url']}\n\n{p['text'][:700]}")
        time.sleep(1)
    if own:
        store.close()
    return new_total


def watch(cfg):
    every = int(cfg["telegram"].get("check_every_min", 5))
    store = Store("telegram")
    print(f"[telegram] проверяю каналы каждые {every} мин. (Ctrl+C — выход)")
    try:
        while True:
            n = scan(cfg, store, quiet=True)
            store.db.commit()
            store.f.flush()
            print(f"  {datetime.now():%H:%M} новых: {n}")
            time.sleep(every * 60)
    finally:
        store.close()


def run(cfg, mode="scan"):
    watch(cfg) if mode == "watch" else scan(cfg)
