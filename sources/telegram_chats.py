"""Поиск заказов в Telegram-чатах (Telethon, ваш личный аккаунт).

scan  — просмотреть последние N сообщений в чатах из config.yaml
watch — слушать чаты в реальном времени и пересылать находки в «Избранное»
"""
import asyncio

from common import BASE, Store, matches

try:
    from telethon import TelegramClient, events
except ImportError:  # pragma: no cover
    TelegramClient = None


def _client(cfg):
    tg = cfg["telegram"]
    if TelegramClient is None:
        raise RuntimeError("Установите telethon: pip install telethon")
    if not tg.get("api_id") or not tg.get("api_hash"):
        raise RuntimeError("Заполните telegram.api_id и api_hash в config.yaml (https://my.telegram.org)")
    return TelegramClient(str(BASE / "data" / "tg_session"), int(tg["api_id"]), tg["api_hash"])


def _link(chat, msg_id):
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{msg_id}"
    return f"https://t.me/c/{chat.id}/{msg_id}"


def _sender_contact(sender):
    if not sender:
        return ""
    u = getattr(sender, "username", None)
    return f"@{u}" if u else str(getattr(sender, "id", ""))


async def _save(client, store, cfg, chat, msg):
    sender = await msg.get_sender()
    url = _link(chat, msg.id)
    lead = {
        "source": f"Telegram: {getattr(chat, 'title', '') or getattr(chat, 'username', '')}",
        "title": (msg.text or "").split("\n")[0][:120],
        "company": _sender_contact(sender),
        "url": url,
        "text": msg.text,
        "notes": msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "",
    }
    if store.add(lead, key=url) and cfg["telegram"].get("notify_saved_messages"):
        await client.send_message("me", f"🔔 Лид: {lead['source']}\nАвтор: {lead['company']}\n{url}\n\n{(msg.text or '')[:700]}")


async def _scan(cfg):
    client = _client(cfg)
    store = Store("telegram")
    async with client:
        for name in cfg["telegram"]["chats"]:
            try:
                chat = await client.get_entity(name)
            except Exception as e:
                print(f"  ! чат {name}: {e}")
                continue
            print(f"[telegram] {name}")
            async for msg in client.iter_messages(chat, limit=cfg["telegram"].get("history_limit", 300)):
                if msg.text and matches(msg.text, cfg):
                    await _save(client, store, cfg, chat, msg)
    store.close()


async def _watch(cfg):
    client = _client(cfg)
    store = Store("telegram")
    await client.start()
    chats = []
    for name in cfg["telegram"]["chats"]:
        try:
            chats.append(await client.get_entity(name))
        except Exception as e:
            print(f"  ! чат {name}: {e}")

    @client.on(events.NewMessage(chats=chats))
    async def handler(event):
        if event.raw_text and matches(event.raw_text, cfg):
            chat = await event.get_chat()
            await _save(client, store, cfg, chat, event.message)
            store.db.commit()
            store.f.flush()
            print(f"  + лид из {getattr(chat, 'title', '')}")

    print(f"[telegram] слушаю {len(chats)} чатов... (Ctrl+C — выход)")
    try:
        await client.run_until_disconnected()
    finally:
        store.close()


def run(cfg, mode="scan"):
    asyncio.run(_watch(cfg) if mode == "watch" else _scan(cfg))


# ---------- помощники для настройки из меню ----------
async def _login(cfg):
    client = _client(cfg)
    await client.start()  # спросит телефон и код из Telegram
    me = await client.get_me()
    await client.disconnect()
    return f"{me.first_name or ''} (@{me.username})" if me.username else (me.first_name or str(me.id))


async def _search(cfg, query, limit=20):
    from telethon.tl.functions.contacts import SearchRequest
    client = _client(cfg)
    async with client:
        res = await client(SearchRequest(q=query, limit=limit))
        out = []
        for ch in res.chats:
            if not getattr(ch, "username", None):
                continue
            out.append({
                "username": ch.username,
                "title": getattr(ch, "title", ""),
                "members": getattr(ch, "participants_count", None) or 0,
                "type": "канал" if getattr(ch, "broadcast", False) else "чат",
            })
        return out


async def _check(cfg):
    client = _client(cfg)
    rows = []
    async with client:
        for name in cfg["telegram"]["chats"]:
            try:
                ent = await client.get_entity(name)
                last = None
                async for m in client.iter_messages(ent, limit=1):
                    last = m.date
                rows.append((name, getattr(ent, "title", ""), last.strftime("%Y-%m-%d") if last else "—", "ok"))
            except Exception as e:
                rows.append((name, "", "", f"ошибка: {str(e)[:50]}"))
    return rows


def login(cfg):
    return asyncio.run(_login(cfg))


def search_chats(cfg, query):
    return asyncio.run(_search(cfg, query))


def check_chats(cfg):
    return asyncio.run(_check(cfg))
