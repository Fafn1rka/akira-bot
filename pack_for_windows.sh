#!/usr/bin/env bash
# Собирает akira-data.zip — твои ЛИЧНЫЕ файлы для переноса на Windows:
#   • .env   (ключи, токены, настройки)
#   • data/  (память Акиры: факты о тебе, история, сценарии)
# Запускать в папке Акиры на Linux:   ./pack_for_windows.sh
# (если пишет «Permission denied»:    chmod +x pack_for_windows.sh)
#
# НЕ кладётся в архив: .venv (программы для Linux на Windows не работают), кэши, логи.
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "Не нашла файл .env в $(pwd)"
    echo "Запусти скрипт в папке, где ты запускаешь Акиру (там лежит main.py)."
    exit 1
fi

OUT="akira-data.zip"
python3 - "$OUT" <<'PY'
import os, re, sys, zipfile

out = sys.argv[1]
if os.path.exists(out):
    os.remove(out)

# .env: сбрасываем то, что привязано к ЭТОМУ компьютеру (номер микрофона на Windows будет другим)
env = open(".env", encoding="utf-8").read()
env = re.sub(r"(?m)^(VOICE_MIC_DEVICE)=.*$", r"\1=", env)

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr(".env", env)
    count = 0
    if os.path.isdir("data"):
        for root, _dirs, files in os.walk("data"):
            for name in files:
                path = os.path.join(root, name)
                z.write(path, path.replace(os.sep, "/"))
                count += 1
print(f"В архив положила: .env и {count} файл(ов) из data/")
PY

echo
echo "Готово: $(pwd)/$OUT"
echo "ВНИМАНИЕ: внутри ключи и токены. Переноси флешкой или по локальной сети,"
echo "не отправляй по почте и в мессенджерах и никому не показывай."
echo "Дальше — файл WINDOWS_SETUP.md."
