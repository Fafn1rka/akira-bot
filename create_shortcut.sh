#!/usr/bin/env bash
# Создаёт значок «Акира» в меню приложений и на рабочем столе — окно открывается как обычная
# программа, без терминала. Запусти один раз (после ./install.sh).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -x "$DIR/.venv/bin/python" ]; then
    echo "Сначала запусти ./install.sh"
    exit 1
fi
chmod +x "$DIR/run_gui.sh"

ICON="$DIR/assets/akira_icon.png"
[ -f "$ICON" ] || ICON="applications-multimedia"

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
FILE="$APPS/akira.desktop"
cat > "$FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Акира
Comment=Голосовой ИИ-компаньон
Exec="$DIR/run_gui.sh"
Path=$DIR
Icon=$ICON
Terminal=false
Categories=Utility;AudioVideo;
DESKTOP
chmod +x "$FILE"
echo "Значок создан в меню приложений: $FILE"

DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESK" ]; then
    cp "$FILE" "$DESK/akira.desktop"
    chmod +x "$DESK/akira.desktop"
    # Cinnamon/GNOME иначе покажут «недоверенный запускатель» и не откроют
    gio set "$DESK/akira.desktop" metadata::trusted true 2>/dev/null || true
    echo "Значок создан на рабочем столе: $DESK/akira.desktop"
fi
echo "Готово. Если значок на столе не открывается — ПКМ по нему -> «Разрешить запуск»."
