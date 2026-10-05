"""Анализ сайтов компаний: контакты + признаки устаревшего сайта (повод предложить редизайн).

Источник URL: файл sites.txt (по одному на строку) или колонка website из data/maps.csv.
"""
import csv
import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from common import BASE, DATA, HEADERS, Store, find_emails, find_phones

CONTACT_PATHS = ["/contacts", "/contact", "/kontakty", "/contacts/"]


def _load_urls(path=None):
    urls = []
    p = BASE / (path or "sites.txt")
    if p.exists():
        urls += [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    maps_csv = DATA / "maps.csv"
    if not path and maps_csv.exists():
        with open(maps_csv, encoding="utf-8-sig") as f:
            urls += [r["website"] for r in csv.DictReader(f) if r.get("website")]
    out = []
    for u in urls:
        if not u.startswith("http"):
            u = "http://" + u
        if u not in out:
            out.append(u)
    return out


def analyze(url, cfg):
    t = cfg["sites"].get("timeout", 15)
    start = time.time()
    r = requests.get(url, headers=HEADERS, timeout=t, allow_redirects=True)
    load = time.time() - start
    r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    texts = [html]
    mailto = [a["href"][7:].split("?")[0] for a in soup.select('a[href^="mailto:"]')]
    tel = [a["href"][4:] for a in soup.select('a[href^="tel:"]')]

    if cfg["sites"].get("check_contacts_page", True):
        links = [a["href"] for a in soup.find_all("a", href=True)
                 if re.search(r"contact|kontakt|контакт", a["href"] + a.get_text(), re.I)]
        for path in (links[:1] or CONTACT_PATHS[:2]):
            try:
                cr = requests.get(urljoin(r.url, path), headers=HEADERS, timeout=t)
                if cr.ok:
                    texts.append(cr.text)
                    break
            except Exception:
                pass

    all_text = "\n".join(texts)
    emails = list(dict.fromkeys(mailto + find_emails(all_text)))
    phones = list(dict.fromkeys(find_phones(" ".join(tel)) + find_phones(BeautifulSoup(all_text, "html.parser").get_text(" "))))

    # --- признаки устаревшего сайта ---
    problems = []
    if not r.url.startswith("https"):
        problems.append("нет HTTPS")
    if not soup.find("meta", attrs={"name": "viewport"}):
        problems.append("не адаптирован под мобильные")
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–—]\s*)?(\d{4})", html, re.I)]
    if years and max(years) < datetime.now().year - 2:
        problems.append(f"копирайт {max(years)} г.")
    if load > 4:
        problems.append(f"медленный ({load:.1f} c)")
    if re.search(r"jquery[-.]?1\.\d|\.swf|<table[^>]+width=", html, re.I):
        problems.append("старые технологии")
    if not soup.find("title") or not soup.title.get_text(strip=True):
        problems.append("нет title")
    if not soup.find("meta", attrs={"name": "description"}):
        problems.append("нет meta description")

    title = soup.title.get_text(strip=True) if soup.title else urlparse(r.url).netloc
    return {
        "source": "Сайт",
        "title": title[:150],
        "company": urlparse(r.url).netloc,
        "website": r.url,
        "url": r.url,
        "phone": ", ".join(phones[:3]),
        "email": ", ".join(emails[:3]),
        "score": len(problems),
        "notes": "; ".join(problems),
    }


def run(cfg, path=None):
    urls = _load_urls(path)
    if not urls:
        print("[sites] добавьте адреса в sites.txt или сначала запустите maps")
        return
    store = Store("sites")
    for i, u in enumerate(urls, 1):
        print(f"[sites] {i}/{len(urls)} {u}")
        try:
            lead = analyze(u, cfg)
            store.add(lead, key=urlparse(lead["url"]).netloc)
        except Exception as e:
            print(f"  ! {type(e).__name__}: {str(e)[:100]}")
    store.close()
    print("  Чем выше score, тем больше проблем у сайта — тем горячее лид.")
