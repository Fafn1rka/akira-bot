#!/usr/bin/env bash
# Установка Акиры на Linux / macOS.
#   chmod +x install.sh && ./install.sh
set -e
cd "$(dirname "$0")"

echo "== Акира: установка (Linux/macOS) =="

if ! command -v python3 >/dev/null 2>&1; then
    echo "Не найден python3. Поставь Python 3.10+ и запусти скрипт снова."
    exit 1
fi

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo ">>> Создан файл .env — открой его и впиши GEMINI_API_KEY (и, если нужно, TELEGRAM_BOT_TOKEN)."
fi

echo
if command -v apt-get >/dev/null 2>&1; then
    echo "Подсказка (Debian/Ubuntu/Mint): для микрофона, звука и голоса в Discord нужно:"
    echo "    sudo apt-get install -y libportaudio2 portaudio19-dev libopus0 ffmpeg libxcb-cursor0"
    echo "(libxcb-cursor0 нужна окну Акиры: без неё Qt пишет ошибку про плагин xcb.)"
    echo "А для управления плеером голосом (пауза / следующий трек) — ещё:"
    echo "    sudo apt-get install -y playerctl"
elif command -v dnf >/dev/null 2>&1; then
    echo "Подсказка (Fedora): sudo dnf install -y portaudio-devel opus ffmpeg playerctl"
elif command -v pacman >/dev/null 2>&1; then
    echo "Подсказка (Arch): sudo pacman -S portaudio opus ffmpeg playerctl"
fi

echo
echo "Готово! Запуск:  source .venv/bin/activate && python3 main.py"
echo "(или просто ./run.sh)"
