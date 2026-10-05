#!/usr/bin/env bash
# Установка парсера на Ubuntu
set -e
cd "$(dirname "$0")"
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
touch sites.txt
chmod +x parser
# команда leads из любой папки
mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/parser" "$HOME/.local/bin/leads"
echo
echo "Готово! Запуск программы:  leads   (или ./parser в этой папке)"
echo "Если команда leads не найдена — откройте новый терминал."
