#!/usr/bin/env python3
"""Парсер клиентов — терминальная программа с меню.  Запуск:  ./parser  (или python app.py)"""
import csv
import os
import shutil
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from common import BASE, DATA, export_excel, load_config  # noqa: E402

# ---------------- оформление ----------------
C = {"r": "\033[31m", "g": "\033[32m", "y": "\033[33m", "b": "\033[34m", "m": "\033[35m",
     "c": "\033[36m", "w": "\033[1m", "d": "\033[2m", "0": "\033[0m"}
WIN = os.name == "nt"
if WIN:
    os.system("")  # включает цвета (ANSI) в консоли Windows
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    C = {k: "" for k in C}


def col(text, c):
    return f"{C[c]}{text}{C['0']}"


def clear():
    if sys.stdout.isatty():
        os.system("cls" if WIN else "clear")


def width():
    return min(shutil.get_terminal_size((90, 30)).columns, 120)


def header(title):
    clear()
    w = width()
    print(col("═" * w, "c"))
    print(col(f"  🔎 ПАРСЕР КЛИЕНТОВ  ·  {title}", "w"))
    print(col("═" * w, "c"))


def ok(msg):
    print(col(f"✔ {msg}", "g"))


def err(msg):
    print(col(f"✖ {msg}", "r"))


def info(msg):
    print(col(msg, "d"))


def ask(prompt, default=None):
    tail = f" [{default}]" if default not in (None, "") else ""
    try:
        v = input(col(f"{prompt}{tail}: ", "y")).strip()
    except EOFError:
        v = ""
    return v if v else ("" if default is None else str(default))


def yes(prompt, default=True):
    v = ask(f"{prompt} (д/н)", "д" if default else "н").lower()
    return v in ("д", "да", "y", "yes", "l")


def pause():
    try:
        input(col("\nНажмите Enter, чтобы продолжить…", "d"))
    except EOFError:
        pass


def menu(title, items, back="Назад"):
    """items: list of (key, label, hint). Возвращает выбранный ключ."""
    header(title)
    for key, label, hint in items:
        if key == "-":
            print(col(f"  {label}", "m"))
            continue
        h = col(f"  {hint}", "d") if hint else ""
        print(f"  {col(key.rjust(2), 'c')}  {label}{h}")
    print(f"  {col(' 0', 'c')}  {back}")
    print()
    return ask("Выбор").lower()


# ---------------- конфиг ----------------
def save_config(cfg):
    p = BASE / "config.yaml"
    bak = BASE / "config.example.yaml"
    if not bak.exists():
        shutil.copy(p, bak)  # исходник с комментариями сохраняем один раз
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=1000)
    ok("Настройки сохранены")


def edit_list(cfg, path, title, hint=""):
    """Редактор списка строк в cfg по пути ('maps','niches')."""
    node = cfg
    for k in path[:-1]:
        node = node[k]
    key = path[-1]
    node[key] = list(node.get(key) or [])
    while True:
        header(title)
        if hint:
            info(hint + "\n")
        items = node[key]
        if not items:
            info("  (пусто)")
        for i, it in enumerate(items, 1):
            print(f"  {col(str(i).rjust(3), 'c')}. {it}")
        print()
        print(f"  {col('+', 'g')} добавить (можно несколько через запятую)   "
              f"{col('-', 'r')} удалить (номера через пробел)   {col('0', 'c')} назад")
        a = ask("Действие")
        if a == "0" or a == "":
            return
        if a.startswith("+"):
            raw = a[1:].strip() or ask("Что добавить")
            for x in [s.strip() for s in raw.split(",") if s.strip()]:
                if x not in items:
                    items.append(x)
            save_config(cfg)
        elif a.startswith("-"):
            raw = a[1:].strip() or ask("Номера для удаления")
            nums = sorted({int(n) for n in raw.replace(",", " ").split() if n.isdigit()}, reverse=True)
            for n in nums:
                if 1 <= n <= len(items):
                    items.pop(n - 1)
            save_config(cfg)


# ---------------- запуск источников ----------------
def run_task(name, fn, *args):
    header(name)
    info("Ctrl+C — остановить и вернуться в меню\n")
    try:
        fn(*args)
    except KeyboardInterrupt:
        print()
        err("Остановлено")
    except RuntimeError as e:
        err(str(e))
    except Exception as e:
        err(f"{type(e).__name__}: {e}")
        if os.environ.get("DEBUG"):
            traceback.print_exc()
    pause()


def do_freelance(cfg):
    from sources import freelance
    run_task("Фриланс-биржи", freelance.run, cfg)


def tg_module(cfg):
    if cfg["telegram"].get("mode", "web") == "api":
        from sources import telegram_chats as m
    else:
        from sources import telegram_web as m
    return m


def do_tg_scan(cfg):
    if not cfg["telegram"].get("chats"):
        header("Telegram")
        err("Список каналов пуст: Настройки → Telegram → Каналы")
        pause()
        return
    run_task("Telegram — скан каналов", tg_module(cfg).run, cfg, "scan")


def do_tg_watch(cfg):
    run_task("Telegram — слежение", tg_module(cfg).run, cfg, "watch")


def do_maps(cfg):
    from sources import maps
    m = cfg["maps"]
    header("Карты")
    print(f"  Ниши:   {', '.join(m['niches']) or '—'}")
    print(f"  Города: {', '.join(m['cities']) or '—'}")
    print(f"  2ГИС:   {'ключ задан' if m.get('dgis_key') else col('нет ключа (только OSM)', 'y')}")
    print(f"  Только без сайта: {'да' if m.get('only_without_site') else 'нет'}\n")
    if not m["niches"] or not m["cities"]:
        err("Добавьте ниши и города: Настройки → Карты")
        pause()
        return
    if yes("Запускаем?"):
        run_task("Карты", maps.run, cfg)


def do_sites(cfg):
    from sources import sites
    run_task("Анализ сайтов", sites.run, cfg, None)


def do_all(cfg):
    def _all():
        from sources import freelance, maps, sites
        for title, fn, args in [("Фриланс", freelance.run, (cfg,)), ("Карты", maps.run, (cfg,)),
                                ("Сайты", sites.run, (cfg, None))]:
            print(col(f"\n▶ {title}", "w"))
            try:
                fn(*args)
            except Exception as e:
                err(f"{title}: {e}")
        if cfg["telegram"].get("chats"):
            print(col("\n▶ Telegram", "w"))
            try:
                tg_module(cfg).run(cfg, "scan")
            except Exception as e:
                err(f"Telegram: {e}")
        export_excel()
    run_task("Запуск всех источников", _all)


# ---------------- просмотр лидов ----------------
def read_csv(name):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def cut(s, n):
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


SHOW = {
    "freelance": [("found_at", 16), ("source", 8), ("title", 50), ("url", 40)],
    "telegram": [("found_at", 16), ("company", 16), ("title", 50), ("url", 34)],
    "maps": [("company", 28), ("city", 13), ("phone", 14), ("website", 24), ("score", 10)],
    "sites": [("score", 5), ("company", 26), ("phone", 14), ("email", 24), ("notes", 40)],
}


def do_view():
    while True:
        files = {p.stem: p for p in sorted(DATA.glob("*.csv"))}
        items = [(str(i), f"{name}", f"{len(read_csv(name))} шт.") for i, name in enumerate(files, 1)]
        if not items:
            header("Просмотр лидов")
            info("Пока пусто — запустите какой-нибудь источник.")
            pause()
            return
        c = menu("Просмотр лидов", items)
        if c in ("0", ""):
            return
        if c.isdigit() and 1 <= int(c) <= len(files):
            view_file(list(files)[int(c) - 1])


def view_file(name):
    rows = read_csv(name)
    q = ""
    page = 0
    per = max(5, shutil.get_terminal_size((90, 30)).lines - 12)
    while True:
        data = [r for r in rows if q.lower() in " ".join(r.values()).lower()] if q else rows
        if name == "sites":
            data = sorted(data, key=lambda r: -int(r.get("score") or 0))
        else:
            data = list(reversed(data))
        pages = max(1, (len(data) + per - 1) // per)
        page = min(page, pages - 1)
        header(f"{name}  ·  {len(data)} шт.  ·  стр. {page + 1}/{pages}" + (f"  ·  фильтр «{q}»" if q else ""))
        cols = SHOW.get(name, [("title", 50), ("url", 40)])
        print("  #   " + "  ".join(col(c.ljust(w), "w") for c, w in cols))
        for i, r in enumerate(data[page * per:(page + 1) * per], page * per + 1):
            print(f"  {str(i).ljust(4)}" + "  ".join(cut(r.get(c, ""), w).ljust(w) for c, w in cols))
        print()
        info("  n/p — след./пред. стр.  ·  /слово — фильтр  ·  номер — подробно  ·  0 — назад")
        a = ask(">")
        if a in ("0", ""):
            return
        if a == "n":
            page += 1
        elif a == "p":
            page = max(0, page - 1)
        elif a.startswith("/"):
            q, page = a[1:].strip(), 0
        elif a.isdigit() and 1 <= int(a) <= len(data):
            header(f"{name} · запись {a}")
            for k, v in data[int(a) - 1].items():
                if v:
                    print(f"  {col(k.ljust(10), 'c')} {v}")
            pause()


def do_stats():
    header("Статистика")
    total = 0
    for p in sorted(DATA.glob("*.csv")):
        rows = read_csv(p.stem)
        total += len(rows)
        today = sum(1 for r in rows if r.get("found_at", "").startswith(__import__("datetime").date.today().isoformat()))
        print(f"  {p.stem.ljust(12)} всего: {col(str(len(rows)).rjust(5), 'w')}   сегодня: {col(str(today), 'g')}")
        if p.stem == "maps":
            nosite = sum(1 for r in rows if not r.get("website"))
            print(f"  {'':12} без сайта: {nosite}")
        if p.stem == "sites":
            hot = sum(1 for r in rows if int(r.get("score") or 0) >= 3)
            print(f"  {'':12} с 3+ проблемами (горячие): {hot}")
    print(f"\n  Итого лидов: {col(str(total), 'w')}")
    pause()


def do_excel():
    run_task("Экспорт в Excel", export_excel)


# ---------------- мастер Telegram ----------------
def tg_settings(cfg):
    tg = cfg["telegram"]
    cfg.setdefault("notify", {"bot_token": "", "chat_id": ""})
    while True:
        mode = tg.get("mode", "web")
        bot = "настроен" if cfg["notify"].get("chat_id") else "не настроен"
        items = [
            ("1", "Режим", "web — без входа, публичные каналы" if mode == "web" else "api — через аккаунт"),
            ("2", "Каналы и чаты (добавить/удалить)", f"{len(tg.get('chats') or [])} шт."),
            ("3", "Проверить каналы", "доступность и дата последнего поста"),
            ("4", "Сколько сообщений смотреть в канале", str(tg.get("history_limit", 100))),
            ("5", "Как часто проверять в режиме слежения", f"{tg.get('check_every_min', 5)} мин."),
            ("6", "Уведомления о лидах через бота", bot),
            ("7", "Где искать каналы с заказами", ""),
        ]
        if mode == "api":
            session = (DATA / "tg_session.session").exists()
            items += [
                ("-", "Режим api (вход в аккаунт)", ""),
                ("8", "Ввести api_id и api_hash", "задано" if tg.get("api_id") else "не задано"),
                ("9", "Войти в Telegram", "выполнен" if session else "не выполнен"),
                ("10", "Найти чаты по слову (поиск Telegram)", ""),
            ]
        c = menu("Настройки · Telegram", items)
        if c in ("0", ""):
            return
        try:
            if c == "1":
                header("Режим Telegram")
                print("""  web — программа читает веб-версию публичных каналов (t.me/s/имя).
        Вход и ключи не нужны. Закрытые чаты не видны.
  api — программа входит в ваш аккаунт и видит все чаты, где вы состоите.
        Нужны api_id/api_hash с my.telegram.org.
""")
                v = ask("Режим (web/api)", mode).lower()
                if v in ("web", "api"):
                    tg["mode"] = v
                    save_config(cfg)
                pause()
            elif c == "2":
                edit_list(cfg, ["telegram", "chats"], "Telegram · каналы",
                          "username без @ или ссылка t.me/… — например FreeVacanciesIT. "
                          "После добавления проверьте их (пункт 3).")
            elif c == "3":
                header("Telegram · проверка каналов")
                info("Проверяю…\n")
                if mode == "api":
                    from sources import telegram_chats
                    rows = telegram_chats.check_chats(cfg)
                else:
                    from sources import telegram_web
                    rows = []
                    for name in tg.get("chats") or []:
                        good, title, last = telegram_web.has_preview(name)
                        rows.append((name, title, last if good else "", "ok" if good else last))
                for name, title, last, status in rows:
                    s_ = col(status, "g" if status == "ok" else "r")
                    print(f"  {cut(name, 24).ljust(24)} {cut(title, 30).ljust(30)} {str(last).ljust(16)} {s_}")
                info("\nКаналы с давним последним постом или ошибкой лучше удалить (пункт 2).")
                pause()
            elif c == "4":
                v = ask("Сколько последних сообщений", tg.get("history_limit", 100))
                if v.isdigit():
                    tg["history_limit"] = int(v)
                    save_config(cfg)
            elif c == "5":
                v = ask("Интервал в минутах", tg.get("check_every_min", 5))
                if v.isdigit() and int(v) >= 1:
                    tg["check_every_min"] = int(v)
                    save_config(cfg)
            elif c == "6":
                bot_settings(cfg)
            elif c == "7":
                header("Где искать каналы с заказами")
                print("""  • В самом Telegram: поиск по словам «фриланс заказы», «заказы сайтов»,
    «ищу разработчика», «IT фриланс», «заказы tilda», «заказы ботов».
  • Подборки каналов: kadrof.ru/articles/38427, vc.ru (статьи «фриланс в Telegram»).
  • Чаты предпринимателей своего города — там просят сделать сайт.

  Берите каналы, где публикуют ЗАКАЗЫ, а не вакансии в штат.
  Имя канала — часть ссылки после t.me/ (t.me/FreeVacanciesIT → FreeVacanciesIT).
  Проверяйте новые каналы пунктом 3: в режиме web работают только те,
  у которых открывается страница t.me/s/имя.""")
                pause()
            elif c == "8" and mode == "api":
                header("Telegram · ключи API")
                v = ask("api_id (число)", tg.get("api_id") or "")
                if not v.isdigit():
                    err("api_id должен быть числом")
                    pause()
                    continue
                tg["api_id"] = int(v)
                tg["api_hash"] = ask("api_hash", tg.get("api_hash") or "")
                save_config(cfg)
                pause()
            elif c == "9" and mode == "api":
                from sources import telegram_chats
                header("Telegram · вход")
                info("Введите номер в формате +79991234567, затем код из Telegram.\n")
                ok(f"Вошли как {telegram_chats.login(cfg)}")
                pause()
            elif c == "10" and mode == "api":
                tg_search(cfg)
        except KeyboardInterrupt:
            print()
        except Exception as e:
            err(f"{type(e).__name__}: {e}")
            pause()


def bot_settings(cfg):
    import notify
    n = cfg["notify"]
    header("Уведомления через бота")
    print("""  Программа будет присылать каждый новый лид вам в Telegram.
  1. Откройте в Telegram @BotFather → /newbot → придумайте имя и username бота
  2. BotFather пришлёт токен вида 123456789:AAH…  — вставьте его ниже
  3. Откройте своего бота и нажмите «Старт» (/start)
""")
    token = ask("Токен бота (Enter — оставить как есть)", "")
    if token:
        good, msg = notify.check_token(token)
        if not good:
            err(msg)
            pause()
            return
        ok(f"Бот найден: {msg}")
        n["bot_token"] = token
        save_config(cfg)
    if not n.get("bot_token"):
        pause()
        return
    if not n.get("chat_id") or yes("Найти chat_id заново?", False):
        ask("Напишите боту /start и нажмите Enter")
        cid, who = notify.find_chat_id(n["bot_token"])
        if not cid:
            err("Боту никто не писал. Нажмите «Старт» в чате с ботом и повторите.")
            pause()
            return
        n["chat_id"] = cid
        save_config(cfg)
        ok(f"chat_id найден ({who})")
    if notify.send(cfg, "✅ Парсер клиентов подключён. Сюда будут приходить новые лиды."):
        ok("Тестовое сообщение отправлено — проверьте Telegram")
    else:
        err("Не удалось отправить тестовое сообщение")
    pause()


def tg_search(cfg):
    from sources import telegram_chats
    tg = cfg["telegram"]
    tg["chats"] = list(tg.get("chats") or [])
    header("Telegram · поиск чатов")
    info("Идеи запросов: фриланс, заказы сайтов, ищу разработчика, предприниматели, бизнес чат <город>, "
         "маркетинг, wildberries селлеры, tilda\n")
    q = ask("Поисковый запрос")
    if not q:
        return
    info("Ищу…")
    res = telegram_chats.search_chats(cfg, q)
    if not res:
        err("Ничего не найдено")
        pause()
        return
    res.sort(key=lambda r: -r["members"])
    header(f"Telegram · «{q}»")
    for i, r in enumerate(res, 1):
        mark = col(" ✓", "g") if r["username"] in tg["chats"] else ""
        print(f"  {col(str(i).rjust(3), 'c')}. {cut(r['title'], 40).ljust(40)} "
              f"{('@' + r['username']).ljust(28)} {str(r['members']).rjust(7)} {r['type']}{mark}")
    info("\nКаналы обычно только публикуют посты; заказы чаще пишут в чатах. Есть и каналы с подборками заказов.")
    a = ask("\nНомера для добавления через пробел (Enter — ничего)")
    added = 0
    for n in a.replace(",", " ").split():
        if n.isdigit() and 1 <= int(n) <= len(res):
            u = res[int(n) - 1]["username"]
            if u not in tg["chats"]:
                tg["chats"].append(u)
                added += 1
    if added:
        save_config(cfg)
        ok(f"Добавлено чатов: {added}")
    pause()


# ---------------- мастер карт ----------------
def maps_settings(cfg):
    m = cfg["maps"]
    while True:
        c = menu("Настройки · Карты", [
            ("1", "Ниши (кого ищем)", cut(", ".join(m.get("niches") or []), 50)),
            ("2", "Города", cut(", ".join(m.get("cities") or []), 50)),
            ("3", "Ключ 2ГИС", "задан" if m.get("dgis_key") else "не задан"),
            ("4", "Проверить ключ 2ГИС", ""),
            ("5", "Страниц 2ГИС на нишу+город (10 компаний/стр.)", str(m.get("dgis_pages", 5))),
            ("6", "Использовать OpenStreetMap (бесплатно)", "да" if m.get("use_osm", True) else "нет"),
            ("7", "Сохранять только компании БЕЗ сайта", "да" if m.get("only_without_site") else "нет"),
            ("8", "Как получить ключ 2ГИС — инструкция", ""),
        ])
        if c in ("0", ""):
            return
        if c == "1":
            from sources.maps import OSM_TAGS
            edit_list(cfg, ["maps", "niches"], "Карты · ниши",
                      "Для OSM лучше всего работают: " + ", ".join(OSM_TAGS))
        elif c == "2":
            edit_list(cfg, ["maps", "cities"], "Карты · города",
                      "Названия как на карте: Москва, Санкт-Петербург, Нижний Новгород…")
        elif c == "3":
            header("Ключ 2ГИС")
            m["dgis_key"] = ask("Вставьте ключ", m.get("dgis_key") or "")
            save_config(cfg)
            if m["dgis_key"]:
                from sources.maps import check_dgis_key
                good, msg = check_dgis_key(m["dgis_key"])
                (ok if good else err)(msg)
            pause()
        elif c == "4":
            from sources.maps import check_dgis_key
            header("Проверка ключа 2ГИС")
            if not m.get("dgis_key"):
                err("Ключ не задан")
            else:
                good, msg = check_dgis_key(m["dgis_key"])
                (ok if good else err)(msg)
            pause()
        elif c == "5":
            v = ask("Страниц", m.get("dgis_pages", 5))
            if v.isdigit():
                m["dgis_pages"] = int(v)
                save_config(cfg)
        elif c == "6":
            m["use_osm"] = not m.get("use_osm", True)
            save_config(cfg)
        elif c == "7":
            m["only_without_site"] = not m.get("only_without_site")
            save_config(cfg)
        elif c == "8":
            header("Как получить ключ 2ГИС")
            print("""  1. Откройте https://platform.2gis.ru (или dev.2gis.ru) и зарегистрируйтесь
  2. В личном кабинете создайте ключ / возьмите демо-ключ
     (демо — бесплатно, но с лимитом запросов и сроком действия)
  3. Нужен доступ к Places API (Catalog API, поиск организаций)
  4. Вставьте ключ сюда (пункт 3) и нажмите «Проверить»

  Без ключа программа ищет только по OpenStreetMap — бесплатно,
  но компаний и телефонов там заметно меньше, чем в 2ГИС.""")
            pause()


def settings(cfg):
    while True:
        c = menu("Настройки", [
            ("1", "Telegram и уведомления", "каналы, бот"),
            ("2", "Карты", "ниши, города, 2ГИС"),
            ("3", "Ключевые слова", f"{len(cfg.get('keywords') or [])} шт."),
            ("4", "Стоп-слова", f"{len(cfg.get('stop_words') or [])} шт."),
            ("5", "RSS-ленты бирж", f"{len(cfg['freelance']['feeds'])} шт."),
            ("6", "Список сайтов для анализа (sites.txt)", ""),
            ("7", "Сбросить базу повторов", "лиды начнут собираться заново"),
        ])
        if c in ("0", ""):
            return
        if c == "1":
            tg_settings(cfg)
        elif c == "2":
            maps_settings(cfg)
        elif c == "3":
            edit_list(cfg, ["keywords"], "Ключевые слова",
                      "Лид засчитывается, если в тексте есть хотя бы одно. Можно часть слова: «разработ» найдёт «разработка», «разработчик».")
        elif c == "4":
            edit_list(cfg, ["stop_words"], "Стоп-слова", "Объявления с этими словами отбрасываются.")
        elif c == "5":
            feeds_settings(cfg)
        elif c == "6":
            sites_list()
        elif c == "7":
            header("Сброс базы повторов")
            if yes("Удалить data/seen.db? CSV-файлы останутся", False):
                (DATA / "seen.db").unlink(missing_ok=True)
                ok("Сброшено")
            pause()


def feeds_settings(cfg):
    feeds = cfg["freelance"]["feeds"]
    while True:
        header("RSS-ленты")
        for i, f in enumerate(feeds, 1):
            print(f"  {col(str(i).rjust(3), 'c')}. {f['name'].ljust(20)} {f['url']}")
        print(f"\n  {col('+', 'g')} добавить   {col('-', 'r')} удалить   {col('0', 'c')} назад")
        a = ask("Действие")
        if a in ("0", ""):
            return
        if a.startswith("+"):
            name, url = ask("Название"), ask("URL ленты")
            if url:
                feeds.append({"name": name or url, "url": url})
                save_config(cfg)
        elif a.startswith("-"):
            n = (a[1:].strip() or ask("Номер"))
            if n.isdigit() and 1 <= int(n) <= len(feeds):
                feeds.pop(int(n) - 1)
                save_config(cfg)


def sites_list():
    p = BASE / "sites.txt"
    p.touch()
    while True:
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        header("Сайты для анализа (sites.txt)")
        info("Сайты из результатов карт добавляются автоматически.\n")
        for i, l in enumerate(lines, 1):
            print(f"  {col(str(i).rjust(3), 'c')}. {l}")
        print(f"\n  {col('+', 'g')} добавить (через запятую/пробел)   {col('-', 'r')} удалить номера   {col('0', 'c')} назад")
        a = ask("Действие")
        if a in ("0", ""):
            return
        if a.startswith("+"):
            raw = a[1:].strip() or ask("Сайты")
            lines += [s for s in raw.replace(",", " ").split() if s not in lines]
        elif a.startswith("-"):
            nums = {int(n) for n in (a[1:].strip() or ask("Номера")).replace(",", " ").split() if n.isdigit()}
            lines = [l for i, l in enumerate(lines, 1) if i not in nums]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------- рассылка ----------------
MAIL_PROVIDERS = {
    "1": ("Яндекс", "smtp.yandex.ru", 465, "id.yandex.ru → Безопасность → Пароли приложений → Почта"),
    "2": ("Mail.ru", "smtp.mail.ru", 465, "Настройки почты → Безопасность → Пароли для внешних приложений"),
    "3": ("Gmail", "smtp.gmail.com", 465, "myaccount.google.com/apppasswords (нужна двухэтапная проверка)"),
}


def outreach_menu(cfg):
    import outreach
    while True:
        cfg = load_config()
        o = cfg["outreach"]
        st = outreach.stats()
        problem = outreach.check_ready(cfg)
        auto = col("ВКЛ", "g") if o.get("enabled") else col("выкл", "r")
        c = menu(f"Рассылка  ·  авто: {auto}  ·  сегодня {st['today']}/{o.get('daily_limit')}  ·  "
                 f"ответов {st['replied']}", [
            ("1", "Очередь и статистика", ""),
            ("2", "Предпросмотр писем", "ничего не отправляет"),
            ("3", "Отправить сейчас", "в пределах дневного лимита"),
            ("4", "Проверить ответы", "IMAP"),
            ("-", "НАСТРОЙКИ", ""),
            ("5", "Почта и подпись", o.get("smtp_user") or "не настроена"),
            ("6", "Лимиты и расписание", f"{o.get('daily_limit')}/день, {o.get('hour_from')}–{o.get('hour_to')} ч"),
            ("7", "Шаблоны писем", "откроются в редакторе"),
            ("8", "Стоп-лист", f"{len(outreach.load_stoplist())} адр."),
            ("9", "Автоотправка: " + ("выключить" if o.get("enabled") else "включить"), problem),
            ("10", "Фоновый автозапуск (systemd)", "биржи, Telegram, карты, рассылка"),
        ])
        if c in ("0", ""):
            return
        if c == "1":
            header("Очередь рассылки")
            q = outreach.build_queue(cfg)
            print(f"Отправлено всего: {st['total']}   сегодня: {st['today']}   ответили: {st['replied']}   "
                  f"отказ: {st['stop']}   не дошло: {st['bounce'] + st['bad']}\n")
            print(col(f"В очереди: {len(q)}", "w"))
            for it in q[:25]:
                kind = "без сайта" if it["kind"] == "no_site" else "проблемы сайта"
                print(f"  {cut(it['email'], 34).ljust(34)} {cut(it['company'], 30).ljust(30)} {col(kind, 'd')}")
            if len(q) > 25:
                info(f"  … и ещё {len(q) - 25}")
            if not q:
                info("Пусто: нужны компании с email — запустите Карты и Анализ сайтов.")
            pause()
        elif c == "2":
            run_task("Предпросмотр", outreach.run, cfg, True, False, 3)
        elif c == "3":
            header("Отправить сейчас")
            if problem:
                err(problem)
            elif yes("Отправить письма из очереди прямо сейчас (без учёта расписания)?", False):
                run_task("Отправка", outreach.run, cfg, False, True)
                continue
            pause()
        elif c == "4":
            run_task("Ответы", outreach.check_replies, cfg)
        elif c == "5":
            mail_settings(cfg)
        elif c == "6":
            limits_settings(cfg)
        elif c == "7":
            editor = os.environ.get("EDITOR") or ("notepad" if WIN else "nano")
            header("Шаблоны писем")
            print((BASE / "templates" / "README.txt").read_text(encoding="utf-8"))
            k = ask("1 — компаниям без сайта, 2 — сайтам с проблемами", "1")
            name = "no_site" if k == "1" else "site_problems"
            os.system(f'{editor} "{BASE / "templates" / (name + ".txt")}"')
        elif c == "8":
            os.system(f'{os.environ.get("EDITOR") or ("notepad" if WIN else "nano")} "{outreach.STOPLIST}"')
        elif c == "9":
            header("Автоотправка")
            if o.get("enabled"):
                o["enabled"] = False
                save_config(cfg)
            elif problem:
                err(problem)
            else:
                info("Письма будут уходить сами, когда работает фоновый автозапуск (пункт 10),\n"
                     f"не больше {o.get('daily_limit')} в день, с {o.get('hour_from')} до {o.get('hour_to')} ч.\n")
                if yes("Включить?", True):
                    o["enabled"] = True
                    save_config(cfg)
            pause()
        elif c == "10":
            header("Фоновый автозапуск")
            if WIN:
                import autostart_win as aw
                actions = {"install": aw.install, "remove": aw.remove, "logs": aw.logs, "status": aw.status}
            else:
                sh = BASE / "autostart.sh"
                actions = {a: (lambda a=a: os.system(f'"{sh}" {a}')) for a in ("install", "remove", "logs", "status")}
            actions["status"]()
            print()
            info("install — включить, remove — выключить, logs — журнал")
            a = ask("Команда (Enter — назад)")
            if a in actions:
                actions[a]()
                pause()


def mail_settings(cfg):
    import getpass
    import outreach
    o = cfg["outreach"]
    header("Почта для рассылки")
    info("Лучше завести отдельный ящик под рассылку, чтобы не рисковать основным.\n")
    for k, (name, *_rest) in MAIL_PROVIDERS.items():
        print(f"  {col(k, 'c')}  {name}")
    print(f"  {col('4', 'c')}  Другая почта (ввести сервер вручную)")
    p = ask("Почта", "1")
    if p in MAIL_PROVIDERS:
        name, host, port, hint = MAIL_PROVIDERS[p]
        o["smtp_host"], o["smtp_port"], o["imap_host"] = host, port, ""
        info(f"\nНужен пароль приложения: {hint}")
    else:
        o["smtp_host"] = ask("SMTP-сервер", o.get("smtp_host"))
        o["smtp_port"] = int(ask("Порт (465 или 587)", o.get("smtp_port", 465)))
        o["imap_host"] = ask("IMAP-сервер (Enter — подобрать)", o.get("imap_host") or "")
    o["smtp_user"] = ask("Адрес почты", o.get("smtp_user"))
    pw = getpass.getpass(col("Пароль приложения (не отображается, Enter — оставить прежний): ", "y")).strip()
    if pw:
        o["smtp_password"] = pw.replace(" ", "")
    o["from_name"] = ask("Имя отправителя", o.get("from_name"))
    print()
    info("Подпись: имя, чем занимаетесь, Telegram, телефон, ссылка на портфолио.\n"
         "Пустая строка — закончить ввод. Enter сразу — оставить прежнюю.")
    if o.get("signature"):
        print(col(o["signature"], "d"))
    lines = []
    while True:
        try:
            line = input("  > ")
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line.rstrip())
    if lines:
        o["signature"] = "\n".join(lines)
    save_config(cfg)
    if yes("\nОтправить тестовое письмо себе?", True):
        try:
            ok(f"Отправлено на {outreach.send_test(cfg)} — проверьте ящик (и папку «Спам»)")
        except Exception as e:
            err(outreach.explain(e, cfg))
    pause()


def limits_settings(cfg):
    o = cfg["outreach"]
    header("Лимиты и расписание")
    info("Для обычного ящика безопасно 20–40 писем в день. Больше — растёт риск блокировки.\n")
    for key, label in [("daily_limit", "Писем в день"), ("delay_min_sec", "Пауза между письмами от, сек"),
                       ("delay_max_sec", "Пауза до, сек"), ("hour_from", "Отправлять с (час)"),
                       ("hour_to", "До (час)"), ("min_problems", "Писать сайтам с проблемами не меньше")]:
        v = ask(label, o.get(key))
        if str(v).isdigit():
            o[key] = int(v)
    o["weekdays_only"] = yes("Только по будням?", o.get("weekdays_only", True))
    save_config(cfg)
    pause()


# ---------------- главное меню ----------------
def status_line(cfg):
    t = cfg["telegram"]
    if t.get("mode", "web") == "api":
        tg = "✔ api" if (DATA / "tg_session.session").exists() else "✖ api"
    else:
        tg = f"web, {len(t.get('chats') or [])} кан."
    dg = "✔" if cfg["maps"].get("dgis_key") else "✖"
    n = sum(len(read_csv(p.stem)) for p in DATA.glob("*.csv"))
    bot = "✔" if (cfg.get("notify") or {}).get("chat_id") else "✖"
    mail = "вкл" if (cfg.get("outreach") or {}).get("enabled") else "выкл"
    return f"Telegram {tg}   бот {bot}   2ГИС {dg}   рассылка {mail}   лидов: {n}"


def main():
    while True:
        cfg = load_config()
        c = menu(status_line(cfg), [
            ("-", "ПОИСК", ""),
            ("1", "Фриланс-биржи", "новые заказы"),
            ("2", "Telegram — скан каналов", "последние сообщения"),
            ("3", "Telegram — слежение", "проверка каждые N минут"),
            ("4", "Карты", "компании по нише и городу"),
            ("5", "Анализ сайтов", "контакты + проблемы сайта"),
            ("6", "Запустить всё", ""),
            ("-", "РЕЗУЛЬТАТЫ", ""),
            ("7", "Просмотр лидов", ""),
            ("8", "Статистика", ""),
            ("9", "Экспорт в Excel", "data/leads.xlsx"),
            ("-", "", ""),
            ("r", "Рассылка", "письма компаниям, автозапуск"),
            ("s", "Настройки", "Telegram, карты, ключевые слова"),
        ], back="Выход")
        actions = {"1": do_freelance, "2": do_tg_scan, "3": do_tg_watch, "4": do_maps,
                   "5": do_sites, "6": do_all, "s": settings, "н": settings,
                   "r": outreach_menu, "к": outreach_menu}
        if c in ("0", "q", "й"):
            clear()
            print("Пока! 👋")
            return
        if c in actions:
            actions[c](cfg)
        elif c == "7":
            do_view()
        elif c == "8":
            do_stats()
        elif c == "9":
            do_excel()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nПока! 👋")
