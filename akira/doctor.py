"""Проверка готовности: что установлено, что запущено, что настроено."""
import importlib.util
import os
import socket
import sys

import requests

from .security import audit


def _port_free(port: int) -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def run_checks(cfg: dict, base_dir, skills=None) -> list[tuple[str, str, str]]:
    """[(статус ok/warn/fail, что проверяли, подсказка)]"""
    out = []
    add = lambda st, name, hint="": out.append((st, name, hint))

    add("ok" if sys.version_info >= (3, 11) else "fail", f"Python {sys.version_info.major}.{sys.version_info.minor}",
        "" if sys.version_info >= (3, 11) else "нужен Python 3.11+")
    for mod, need in (("requests", True), ("numpy", False), ("sounddevice", False), ("faster_whisper", False),
                      ("pyttsx3", False)):
        if importlib.util.find_spec(mod):
            add("ok", f"пакет {mod}")
        else:
            add("fail" if need else "warn", f"пакет {mod} не установлен", "pip install -r requirements.txt")

    loc = cfg["local"]
    try:
        tags = requests.get(loc["host"].rstrip("/") + "/api/tags", timeout=2).json().get("models", [])
        names = {m["name"] for m in tags}
        add("ok", "Ollama запущена")
        for key in ("main_model", "fast_model", "embed_model"):
            m = loc[key]
            if m in names or f"{m}:latest" in names:
                add("ok", f"модель {m}")
            else:
                add("warn" if key != "main_model" else "fail", f"модель {m} не скачана", f"ollama pull {m}")
    except (requests.RequestException, ValueError):
        add("fail", "Ollama не отвечает", "запустите Ollama (приложение в трее) или `ollama serve`")

    has_cloud_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    if has_cloud_key:
        provider = "Gemini" if os.environ.get("GEMINI_API_KEY") else "Anthropic"
        add("ok", f"облачный ключ найден ({provider})")
    else:
        add("warn", "нет GEMINI_API_KEY или ANTHROPIC_API_KEY", "без ключа работает только локальная модель (Ollama)")

    if importlib.util.find_spec("sounddevice"):
        try:
            import sounddevice as sd
            sd.query_devices(kind="input")
            add("ok", "микрофон найден")
        except Exception:  # noqa: BLE001
            add("warn", "микрофон не найден", "python run_voice.py --devices")

    ports = [("аватар", cfg["avatar"]["port"])] + ([("телефон", cfg["phone"]["port"])] if cfg["phone"]["enabled"] else [])
    for name, port in ports:
        add("ok" if _port_free(port) else "warn", f"порт {name} {port}" + ("" if _port_free(port) else " занят"),
            "" if _port_free(port) else "возможно, Акира уже запущена или порт занят другой программой")

    for d in cfg["tools"]["allowed_dirs"]:
        p = os.path.expanduser(d)
        if not os.path.isdir(p):
            add("warn", f"папка {d} не существует", "создайте её или уберите из tools.allowed_dirs")
    for lvl, text in audit(cfg, base_dir, skills):
        if lvl in ("high", "warn"):
            add("fail" if lvl == "high" else "warn", f"безопасность: {text}")
    return out
