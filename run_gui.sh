#!/usr/bin/env bash
# Окно Акиры (чат, статус, сценарии, настройки, журнал). Из терминала показывает вывод как обычно;
# из ярлыка (терминала нет) — пишет его в logs/gui.out, чтобы при проблеме было что посмотреть.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "Сначала запусти ./install.sh"
    exit 1
fi
source .venv/bin/activate
mkdir -p logs
if [ -t 1 ]; then
    exec python gui.py
else
    exec python gui.py >> logs/gui.out 2>&1
fi
