#!/usr/bin/env bash
# Сборка портативной версии для Windows (64-бит): dist/LeadParser-windows.zip
# Внутри — встроенный Python и все библиотеки, установка не нужна. Личные данные
# (config.yaml с паролями, data/, stoplist) в архив НЕ попадают.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
PYVER=3.14.8
PYTAG=314
OUT=dist/LeadParser
CACHE=dist/.cache
mkdir -p "$CACHE"
rm -rf "$OUT" dist/LeadParser-windows.zip

EMBED="$CACHE/python-$PYVER-embed-amd64.zip"
[ -f "$EMBED" ] || curl -fL -o "$EMBED" "https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip"
mkdir -p "$OUT/python" "$OUT/app"
unzip -q "$EMBED" -d "$OUT/python"
printf 'python%s.zip\r\n.\r\nLib\\site-packages\r\n' "$PYTAG" > "$OUT/python/python$PYTAG._pth"

# pyaes (для Telethon) есть только в исходниках — собираем из него универсальный wheel
ls "$CACHE"/pyaes-*.whl >/dev/null 2>&1 || ./venv/bin/pip wheel -q --disable-pip-version-check --no-deps -w "$CACHE" pyaes
./venv/bin/pip install -q --disable-pip-version-check --find-links "$CACHE" --target "$OUT/python/Lib/site-packages" \
  --platform win_amd64 --python-version "$PYVER" --implementation cp --only-binary=:all: -r requirements.txt
find "$OUT/python/Lib/site-packages" -name "__pycache__" -prune -exec rm -rf {} +

# код программы (без личных настроек и результатов)
cp ./*.py config.example.yaml requirements.txt "$OUT/app/"
mkdir -p "$OUT/app/sources" "$OUT/app/templates"
cp sources/*.py "$OUT/app/sources/"
cp templates/*.txt "$OUT/app/templates/"
: > "$OUT/app/sites.txt"
printf '%s\n' "# Стоп-лист рассылки: email или домен (по одному на строку). Им письма не отправляются." \
  "# Отказы из ответов («нет», «не пишите», «отпишите») добавляются сюда автоматически." > "$OUT/app/stoplist.txt"

printf '%s\r\n' '@echo off' 'chcp 65001 >nul' 'set PYTHONUTF8=1' 'set PYTHONIOENCODING=utf-8' \
  'title Lead Parser' 'cd /d "%~dp0app"' '"%~dp0python\python.exe" app.py' 'if errorlevel 1 pause' > "$OUT/START.bat"
sed 's/$/\r/' WINDOWS_README.txt > "$OUT/README.txt"

(cd dist && zip -qr9 LeadParser-windows.zip LeadParser)
echo "Готово: dist/LeadParser-windows.zip ($(du -h dist/LeadParser-windows.zip | cut -f1))"
