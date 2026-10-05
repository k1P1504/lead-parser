"""Новые заказы с фриланс-бирж через RSS/Atom."""
import re
import xml.etree.ElementTree as ET

import requests

import notify
from common import HEADERS, Store, matches


def strip_html(s):
    return re.sub(r"<[^>]+>", " ", s or "")


def parse_feed(content):
    """Возвращает список dict(title, link, summary, published) для RSS 2.0 и Atom."""
    root = ET.fromstring(content)
    for el in root.iter():  # убираем namespace'ы
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    items = []
    for it in root.iter("item"):
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "summary": it.findtext("description") or "",
            "published": it.findtext("pubDate") or "",
        })
    for it in root.iter("entry"):
        link = it.find("link")
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": link.get("href", "") if link is not None else "",
            "summary": it.findtext("summary") or it.findtext("content") or "",
            "published": it.findtext("updated") or it.findtext("published") or "",
        })
    return items


def run(cfg):
    store = Store("freelance")
    for feed in cfg["freelance"]["feeds"]:
        print(f"[freelance] {feed['name']}: {feed['url']}")
        try:
            r = requests.get(feed["url"], headers=HEADERS, timeout=20)
            r.raise_for_status()
            entries = parse_feed(r.content)
        except Exception as e:
            print(f"  ! не удалось загрузить/разобрать: {e}")
            continue
        if not entries:
            print("  ! лента пустая или формат изменился — проверьте URL в config.yaml")
        for e in entries:
            text = strip_html(e["summary"])
            if not matches(f"{e['title']} {text}", cfg):
                continue
            if store.add({
                "source": feed["name"],
                "title": e["title"],
                "url": e["link"],
                "text": text,
                "notes": e["published"],
            }):
                notify.send(cfg, f"🔔 {feed['name']}\n{e['title']}\n{e['link']}\n\n{text.strip()[:700]}")
    store.close()
