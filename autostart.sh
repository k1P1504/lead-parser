#!/usr/bin/env bash
# Фоновая работа парсера через systemd (пользовательские службы, sudo не нужен).
#   ./autostart.sh install   — включить     ./autostart.sh remove — выключить
#   ./autostart.sh status    — состояние    ./autostart.sh logs   — последние записи журнала
set -e
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PY="$DIR/venv/bin/python"
U="$HOME/.config/systemd/user"
UNITS="leads-watch.service leads-auto.service leads-auto.timer leads-daily.service leads-daily.timer"

case "${1:-status}" in
install)
  mkdir -p "$U"
  cat > "$U/leads-watch.service" <<UNIT
[Unit]
Description=Парсер клиентов: слежение за Telegram-каналами
After=network-online.target

[Service]
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY $DIR/leads.py telegram --watch
Restart=always
RestartSec=60

[Install]
WantedBy=default.target
UNIT
  cat > "$U/leads-auto.service" <<UNIT
[Unit]
Description=Парсер клиентов: биржи, ответы и email-рассылка

[Service]
Type=oneshot
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY $DIR/leads.py auto
UNIT
  cat > "$U/leads-auto.timer" <<UNIT
[Unit]
Description=Каждые 30 минут: биржи + рассылка

[Timer]
OnBootSec=3min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  cat > "$U/leads-daily.service" <<UNIT
[Unit]
Description=Парсер клиентов: карты, анализ сайтов, Excel, сводка

[Service]
Type=oneshot
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY $DIR/leads.py daily
UNIT
  cat > "$U/leads-daily.timer" <<UNIT
[Unit]
Description=Раз в день: карты + сайты

[Timer]
OnCalendar=*-*-* 08:00
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable --now leads-watch.service leads-auto.timer leads-daily.timer
  echo "Автозапуск включён. Работает, пока вы вошли в систему."
  ;;
remove)
  systemctl --user disable --now leads-watch.service leads-auto.timer leads-daily.timer 2>/dev/null || true
  for u in $UNITS; do rm -f "$U/$u"; done
  systemctl --user daemon-reload
  echo "Автозапуск выключен."
  ;;
status)
  systemctl --user --no-pager list-timers 'leads-*' 2>/dev/null || true
  systemctl --user --no-pager is-active leads-watch.service >/dev/null 2>&1 \
    && echo "Слежение за Telegram: работает" || echo "Слежение за Telegram: не запущено"
  ;;
logs)
  journalctl --user --no-pager -n "${2:-60}" -u leads-watch -u leads-auto -u leads-daily
  ;;
*) echo "Использование: $0 install|remove|status|logs"; exit 1 ;;
esac
