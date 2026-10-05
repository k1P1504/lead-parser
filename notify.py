"""Уведомления о новых лидах через вашего Telegram-бота (ключи API не нужны, только токен от @BotFather)."""
import requests

API = "https://api.telegram.org/bot{token}/{method}"


def _call(token, method, **params):
    r = requests.post(API.format(token=token, method=method), data=params, timeout=20)
    return r.json()


def send(cfg, text):
    n = cfg.get("notify") or {}
    if not (n.get("bot_token") and n.get("chat_id")):
        return False
    try:
        return _call(n["bot_token"], "sendMessage", chat_id=n["chat_id"], text=text[:4000],
                     disable_web_page_preview="true").get("ok", False)
    except Exception:
        return False


def check_token(token):
    """(ok, имя бота | ошибка)."""
    try:
        res = _call(token, "getMe")
    except Exception as e:
        return False, str(e)
    if res.get("ok"):
        return True, "@" + res["result"]["username"]
    return False, res.get("description", "неверный токен")


def find_chat_id(token):
    """Ищет chat_id того, кто последним написал боту /start."""
    res = _call(token, "getUpdates")
    for upd in reversed(res.get("result", [])):
        msg = upd.get("message") or upd.get("my_chat_member") or {}
        chat = msg.get("chat")
        if chat:
            return chat["id"], chat.get("first_name") or chat.get("title") or ""
    return None, None
