"""
Пауза / следующий / предыдущий трек — в любом плеере (Spotify, браузер, VLC...).

  Windows — имитация медиа-клавиш, ничего ставить не нужно.
  Linux   — через playerctl:  sudo apt install playerctl
"""
from __future__ import annotations

import shutil
import subprocess
import sys

_WIN_VK = {"play_pause": 0xB3, "pause": 0xB3, "play": 0xB3, "next": 0xB0, "previous": 0xB1}
_PLAYERCTL = {"play_pause": "play-pause", "pause": "pause", "play": "play", "next": "next", "previous": "previous"}

ACTIONS = "play_pause, pause, play, next, previous"


def media_key(action: str) -> str:
    action = (action or "").strip().lower()
    if action not in _WIN_VK:
        return f"Неизвестное действие. Доступно: {ACTIONS}."

    if sys.platform == "win32":
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        vk = _WIN_VK[action]
        user32.keybd_event(vk, 0, 0, 0)   # нажать
        user32.keybd_event(vk, 0, 2, 0)   # отпустить (KEYEVENTF_KEYUP)
        return "Готово."

    if sys.platform.startswith("linux"):
        exe = shutil.which("playerctl")
        if not exe:
            return "Для управления плеером на Linux нужна программа playerctl: sudo apt install playerctl"
        try:
            r = subprocess.run([exe, _PLAYERCTL[action]], capture_output=True, text=True, timeout=5)
        except Exception as e:  # noqa: BLE001
            return f"Не получилось управлять плеером: {e}"
        if r.returncode != 0:
            return "Не нашла запущенного плеера, которым можно управлять."
        return "Готово."

    return "Управление плеером на этой системе пока не поддерживается."
