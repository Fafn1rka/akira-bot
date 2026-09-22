"""
Управление компьютером — одинаковый интерфейс на Windows и Linux (и macOS).
Никаких shell-команд от пользователя тут не выполняется: только конкретные,
заранее описанные действия (открыть программу/сайт, громкость, статус).
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import webbrowser
from typing import Optional

import psutil

import config

log = logging.getLogger("akira.system")

_NOWIN = {"creationflags": subprocess.CREATE_NO_WINDOW} if config.IS_WINDOWS else {}

# alias -> (windows, linux, macos); None -> используем webbrowser / общий способ
_APPS: dict[str, dict[str, str]] = {
    "браузер": {"windows": "start", "linux": "xdg-open", "darwin": "open"},
    "калькулятор": {"windows": "calc", "linux": "gnome-calculator", "darwin": "open -a Calculator"},
    "блокнот": {"windows": "notepad", "linux": "gedit", "darwin": "open -a TextEdit"},
    "проводник": {"windows": "explorer", "linux": "xdg-open .", "darwin": "open ."},
    "терминал": {"windows": "wt", "linux": "x-terminal-emulator", "darwin": "open -a Terminal"},
    "диспетчер задач": {"windows": "taskmgr", "linux": "gnome-system-monitor", "darwin": "open -a 'Activity Monitor'"},
    "spotify": {"windows": "spotify", "linux": "spotify", "darwin": "open -a Spotify"},
    "steam": {"windows": "steam", "linux": "steam", "darwin": "open -a Steam"},
    "discord": {"windows": "discord", "linux": "discord", "darwin": "open -a Discord"},
    "vscode": {"windows": "code", "linux": "code", "darwin": "open -a 'Visual Studio Code'"},
    "code": {"windows": "code", "linux": "code", "darwin": "open -a 'Visual Studio Code'"},
}

_SITES = {
    "youtube": "https://youtube.com", "ютуб": "https://youtube.com",
    "google": "https://google.com", "гугл": "https://google.com",
    "телеграм": "https://web.telegram.org", "telegram": "https://web.telegram.org",
    "почта": "https://mail.google.com", "gmail": "https://mail.google.com",
    "github": "https://github.com",
}


def _platkey() -> str:
    return {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}.get(platform.system(), "linux")


def open_app(name: str) -> str:
    """Открывает приложение по-русски/по-английски названное. Возвращает, что получилось."""
    key = name.strip().lower()
    if not config.ENABLE_SYSTEM_COMMANDS:
        return "Управление компьютером сейчас отключено в настройках."

    for site_key, url in _SITES.items():
        if site_key in key:
            webbrowser.open(url)
            return f"Открываю {name} в браузере."

    entry = _APPS.get(key)
    if entry is None:
        for alias, e in _APPS.items():
            if alias in key or key in alias:
                entry = e
                break
    if entry is None:
        # последний шанс — просто попробовать запустить как есть (без shell!)
        exe = shutil.which(key)
        if exe:
            try:
                subprocess.Popen([exe], **_NOWIN)
                return f"Открываю {name}."
            except Exception as e:  # noqa: BLE001
                return f"Не смогла открыть {name}: {e}"
        return f"Не знаю такую программу — {name}."

    cmd = entry.get(_platkey())
    try:
        if config.IS_WINDOWS:
            if os.path.exists(cmd):
                os.startfile(cmd)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(f'start "" {cmd}', shell=True, **_NOWIN)
        elif config.IS_MAC:
            subprocess.Popen(cmd, shell=True)
        else:
            subprocess.Popen(cmd.split() if " " not in cmd or cmd.split()[0] != "xdg-open" else cmd.split(),
                             **_NOWIN)
        return f"Открываю {name}."
    except Exception as e:  # noqa: BLE001
        log.warning("open_app(%s): %s", name, e)
        return f"Не получилось открыть {name}: попробуй проверить, установлена ли программа."


def control_volume(action: str, value: Optional[int] = None) -> str:
    """action: 'up' | 'down' | 'mute' | 'set' (нужен value 0..100)."""
    if not config.ENABLE_SYSTEM_COMMANDS:
        return "Управление громкостью сейчас отключено в настройках."
    try:
        if config.IS_WINDOWS:
            return _volume_windows(action, value)
        if config.IS_MAC:
            return _volume_mac(action, value)
        return _volume_linux(action, value)
    except Exception as e:  # noqa: BLE001
        log.warning("control_volume: %s", e)
        return "Не получилось изменить громкость — на этой системе не нашла подходящий способ."


def _volume_linux(action: str, value: Optional[int]) -> str:
    if shutil.which("wpctl"):  # PipeWire (по умолчанию в новых Ubuntu/Fedora)
        sink = "@DEFAULT_AUDIO_SINK@"
        if action == "mute":
            subprocess.run(["wpctl", "set-mute", sink, "toggle"], **_NOWIN)
            return "Готово, переключила звук."
        if action == "set" and value is not None:
            subprocess.run(["wpctl", "set-volume", sink, f"{max(0,min(100,value))}%"], **_NOWIN)
        else:
            step = "5%+" if action == "up" else "5%-"
            subprocess.run(["wpctl", "set-volume", sink, step], **_NOWIN)
        return "Готово."
    if shutil.which("pactl"):  # PulseAudio
        sink = "@DEFAULT_SINK@"
        if action == "mute":
            subprocess.run(["pactl", "set-sink-mute", sink, "toggle"], **_NOWIN)
        elif action == "set" and value is not None:
            subprocess.run(["pactl", "set-sink-volume", sink, f"{max(0,min(100,value))}%"], **_NOWIN)
        else:
            subprocess.run(["pactl", "set-sink-volume", sink, "+5%" if action == "up" else "-5%"], **_NOWIN)
        return "Готово."
    if shutil.which("amixer"):
        if action == "mute":
            subprocess.run(["amixer", "set", "Master", "toggle"], **_NOWIN)
        elif action == "set" and value is not None:
            subprocess.run(["amixer", "set", "Master", f"{max(0,min(100,value))}%"], **_NOWIN)
        else:
            subprocess.run(["amixer", "set", "Master", "5%+" if action == "up" else "5%-"], **_NOWIN)
        return "Готово."
    return "Не нашла на этой системе ни wpctl, ни pactl, ни amixer для управления громкостью."


def _volume_windows(action: str, value: Optional[int]) -> str:
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except ImportError:
        return "Для управления громкостью на Windows поставь пакет pycaw: pip install pycaw comtypes"
    speakers = AudioUtilities.GetSpeakers()
    iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    vol = cast(iface, POINTER(IAudioEndpointVolume))
    if action == "mute":
        vol.SetMute(not vol.GetMute(), None)
        return "Готово, переключила звук."
    cur = vol.GetMasterVolumeLevelScalar()
    if action == "set" and value is not None:
        vol.SetMasterVolumeLevelScalar(max(0, min(100, value)) / 100, None)
    else:
        cur += 0.05 if action == "up" else -0.05
        vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, cur)), None)
    return "Готово."


def _volume_mac(action: str, value: Optional[int]) -> str:
    if action == "mute":
        subprocess.run(["osascript", "-e", "set volume output muted (output muted of (get volume settings) is false)"])
        return "Готово, переключила звук."
    if action == "set" and value is not None:
        subprocess.run(["osascript", "-e", f"set volume output volume {max(0,min(100,value))}"])
    else:
        cur = 50
        try:
            out = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                                 capture_output=True, text=True).stdout.strip()
            cur = int(out) if out else 50
        except Exception:  # noqa: BLE001
            pass
        cur += 8 if action == "up" else -8
        subprocess.run(["osascript", "-e", f"set volume output volume {max(0,min(100,cur))}"])
    return "Готово."


def run_confirmed_terminal_command(command: str, timeout: int = 25) -> str:
    """
    Выполняет команду терминала. Вызывается ТОЛЬКО после того, как владелец
    явно подтвердил именно эту команду (см. brain.py) — сама по себе функция
    никакой проверки прав не делает, это забота вызывающего кода.
    """
    if not config.ENABLE_TERMINAL_COMMANDS:
        return "Выполнение консольных команд отключено в настройках (.env)."
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True,
                           timeout=timeout, **_NOWIN)
        out = (r.stdout or "") + (r.stderr or "")
        out = out.strip() or "(команда выполнена, вывода нет)"
        if len(out) > 1500:
            out = out[:1500] + "\n…(обрезано)"
        return f"Код завершения {r.returncode}.\n{out}"
    except subprocess.TimeoutExpired:
        return f"Команда не уложилась в {timeout} секунд и была прервана."
    except Exception as e:  # noqa: BLE001
        return f"Не получилось выполнить команду: {e}"


def get_system_status() -> str:
    """Короткая сводка о системе — для голосового ответа."""
    try:
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        parts = [f"Загрузка процессора {cpu:.0f}%", f"память занята {mem.percent:.0f}%"]
        battery = None
        try:
            battery = psutil.sensors_battery()
        except Exception:  # noqa: BLE001
            pass
        if battery is not None:
            state = "заряжается" if battery.power_plugged else "от батареи"
            parts.append(f"батарея {battery.percent:.0f}%, {state}")
        try:
            disk = psutil.disk_usage(os.path.abspath(os.sep))
            parts.append(f"диск занят на {disk.percent:.0f}%")
        except Exception:  # noqa: BLE001
            pass
        return ", ".join(parts) + "."
    except Exception as e:  # noqa: BLE001
        log.warning("get_system_status: %s", e)
        return "Не удалось получить данные о системе."
