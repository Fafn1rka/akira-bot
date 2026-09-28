#!/usr/bin/env bash
# Проверка микрофона: список устройств и распознавание в реальном времени.
cd "$(dirname "$0")"
source .venv/bin/activate
python voice_listener.py --devices
echo
python voice_listener.py --test
