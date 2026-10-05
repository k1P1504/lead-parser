#!/usr/bin/env python3
"""Парсер клиентов. Примеры:
  python leads.py freelance          # новые заказы с бирж
  python leads.py telegram           # скан последних сообщений в чатах
  python leads.py telegram --watch   # слушать чаты в реальном времени
  python leads.py maps               # компании из 2ГИС / OpenStreetMap
  python leads.py sites              # анализ сайтов (sites.txt + сайты из maps)
  python leads.py all                # freelance + maps + sites + telegram scan
  python leads.py excel              # собрать всё в data/leads.xlsx
  python leads.py outreach           # email-рассылка (по расписанию и лимиту из config.yaml)
  python leads.py outreach --dry-run # показать письма, ничего не отправляя
  python leads.py replies            # проверить ответы на рассылку
  python leads.py auto               # для фона, каждые 30 мин: биржи + ответы + рассылка
  python leads.py daily              # для фона, раз в день: карты + сайты + Excel + сводка в бота
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA, export_excel, load_config  # noqa: E402

if sys.stdout is None:  # запуск без консоли (pythonw на Windows) — пишем в журнал
    from datetime import datetime
    _log = DATA / "leads.log"
    if _log.exists() and _log.stat().st_size > 5_000_000:
        _log.replace(DATA / "leads.old.log")
    sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)
    print(f"\n===== {datetime.now():%Y-%m-%d %H:%M} {' '.join(sys.argv[1:])}")


def main():
    ap = argparse.ArgumentParser(description="Парсер клиентов")
    ap.add_argument("source", choices=["freelance", "telegram", "maps", "sites", "all", "excel",
                                       "outreach", "replies", "auto", "daily"])
    ap.add_argument("--watch", action="store_true", help="telegram: режим реального времени")
    ap.add_argument("--file", help="sites: свой файл со списком сайтов")
    ap.add_argument("--dry-run", action="store_true", help="outreach: только показать письма")
    a = ap.parse_args()
    cfg = load_config()

    if a.source in ("auto", "daily"):
        return background(cfg, a.source)
    if a.source == "replies":
        import outreach
        return outreach.check_replies(cfg)
    if a.source == "outreach":
        import outreach
        return outreach.run(cfg, dry_run=a.dry_run)

    if a.source in ("freelance", "all"):
        from sources import freelance
        freelance.run(cfg)
    if a.source in ("maps", "all"):
        from sources import maps
        maps.run(cfg)
    if a.source in ("sites", "all"):
        from sources import sites
        sites.run(cfg, a.file)
    if a.source in ("telegram", "all"):
        if cfg["telegram"].get("mode", "web") == "api":
            from sources import telegram_chats as tg
        else:
            from sources import telegram_web as tg
        if not cfg["telegram"].get("chats"):
            print("[telegram] список каналов пуст — пропускаю")
        else:
            tg.run(cfg, "watch" if a.watch else "scan")
    if a.source in ("excel", "all"):
        export_excel()


def _step(name, fn, *args):
    """В фоне ошибка одного шага не должна останавливать остальные."""
    try:
        fn(*args)
    except Exception as e:
        print(f"[{name}] ошибка: {type(e).__name__}: {e}")


def background(cfg, kind):
    import notify
    import outreach
    from sources import freelance
    if kind == "auto":
        _step("freelance", freelance.run, cfg)
        if cfg["outreach"].get("enabled"):
            _step("replies", outreach.check_replies, cfg)
            _step("outreach", outreach.run, cfg)
        return
    from sources import maps, sites
    before = {p.stem: _count(p) for p in DATA.glob("*.csv")}
    _step("maps", maps.run, cfg)
    _step("sites", sites.run, cfg)
    _step("excel", export_excel)
    lines = []
    for p in sorted(DATA.glob("*.csv")):
        n = _count(p) - before.get(p.stem, 0)
        if n and p.stem != "outreach":
            lines.append(f"  {p.stem}: +{n}")
    st = outreach.stats()
    q = len(outreach.build_queue(cfg))
    notify.send(cfg, "📊 Сводка за день\nНовые лиды:\n" + ("\n".join(lines) or "  нет") +
                f"\n\nРассылка: {'вкл' if cfg['outreach'].get('enabled') else 'ВЫКЛ'}, отправлено всего {st['total']}, "
                f"ответов {st['replied']}, отказов {st['stop']}, в очереди {q}")


def _count(p):
    with open(p, encoding="utf-8-sig") as f:
        return max(sum(1 for _ in f) - 1, 0)


if __name__ == "__main__":
    main()
