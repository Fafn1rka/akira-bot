"""
Настройки Акиры. Всё читается из файла .env (см. .env.example).
Работает одинаково на Windows, Linux и macOS.
"""
from __future__ import annotations

import os
import platform
import re
from pathlib import Path
from typing import List, Tuple

BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except Exception:  # noqa: BLE001  — python-dotenv не установлен: читаем .env вручную
    _p = BASE_DIR / ".env"
    if _p.exists():
        for _line in _p.read_text(encoding="utf-8", errors="ignore").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "да")


def _int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, "").strip()))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip().replace(",", "."))
    except ValueError:
        return default


def _id_list(name: str) -> List[int]:
    out: List[int] = []
    for part in re.split(r"[,\s;]+", os.getenv(name, "")):
        if part.strip().lstrip("-").isdigit():
            out.append(int(part))
    return out


def parse_quiet_hours(spec: str) -> Tuple[int, int] | None:
    """'23:00-08:00' -> (1380, 480) минут от полуночи; пусто/ошибка -> None."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$", spec or "")
    if not m:
        return None
    a = int(m.group(1)) * 60 + int(m.group(2))
    b = int(m.group(3)) * 60 + int(m.group(4))
    return (a, b) if a != b else None


# ─── Папки ────────────────────────────────────────────────────
ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
AUDIO_CACHE = BASE_DIR / "audio_cache"
for _d in (DATA_DIR, LOGS_DIR, AUDIO_CACHE):
    _d.mkdir(exist_ok=True)

# ─── Платформа ────────────────────────────────────────────────
_OS = platform.system()  # "Windows" | "Linux" | "Darwin"
IS_WINDOWS = _OS == "Windows"
IS_LINUX = _OS == "Linux"
IS_MAC = _OS == "Darwin"

# ─── Gemini ───────────────────────────────────────────────────
GEMINI_API_KEY = _str("GEMINI_API_KEY")
GEMINI_MODEL = _str("GEMINI_MODEL", "gemini-3.6-flash")

# ─── Как Акира тебя называет ──────────────────────────────────
OWNER_NAME = _str("OWNER_NAME", "Создатель")

# ─── Голос (Edge-TTS, все голоса ЖЕНСКИЕ) ─────────────────────
VOICE_AKIRA = _str("VOICE_AKIRA", "ru-RU-SvetlanaNeural")
VOICE_UKRAINIAN = _str("VOICE_UKRAINIAN", "uk-UA-PolinaNeural")
VOICE_ENGLISH = _str("VOICE_ENGLISH", "en-US-JennyNeural")
VOICE_RATE = _str("VOICE_RATE", "+0%")      # скорость: -20% … +20%
VOICE_PITCH = _str("VOICE_PITCH", "+0Hz")   # тон: -10Hz … +10Hz
MAX_SPEECH_CHARS = _int("MAX_SPEECH_CHARS", 600)

# ─── Микрофон ─────────────────────────────────────────────────
VOICE_INPUT_ENABLED = _bool("VOICE_INPUT_ENABLED", True)
VOICE_ENERGY_THRESHOLD = _float("VOICE_ENERGY_THRESHOLD", 700)
VOICE_WAKE_WORD_REQUIRED = _bool("VOICE_WAKE_WORD_REQUIRED", True)
VOICE_CONVERSATION_WINDOW = _float("VOICE_CONVERSATION_WINDOW", 25)  # секунд без «Акира»
MIC_SAMPLE_RATE = 16000

# ─── Управление компьютером ───────────────────────────────────
ENABLE_SYSTEM_COMMANDS = _bool("ENABLE_SYSTEM_COMMANDS", True)
ENABLE_TERMINAL_COMMANDS = _bool("ENABLE_TERMINAL_COMMANDS", False)  # опасно, по умолчанию выкл.

# ─── Персонаж на экране ───────────────────────────────────────
ENABLE_AVATAR = _bool("ENABLE_AVATAR", True)
AVATAR_WIDTH = _int("AVATAR_WIDTH", 320)
AVATAR_SHOW_STATUS = _bool("AVATAR_SHOW_STATUS", True)
AVATAR_CLICK_THROUGH = _bool("AVATAR_CLICK_THROUGH", False)

# ─── Сама пишет первой ────────────────────────────────────────
IDLE_CHAT_ENABLED = _bool("IDLE_CHAT_ENABLED", True)
IDLE_CHAT_INTERVAL = _int("IDLE_CHAT_INTERVAL", 45)       # минут тишины
IDLE_MAX_PER_DAY = _int("IDLE_MAX_PER_DAY", 6)
# Пусто по умолчанию = Акира активна круглые сутки. Хочешь тишину ночью —
# впиши в .env, например: QUIET_HOURS=23:00-08:00
QUIET_HOURS = _str("QUIET_HOURS", "")

# ─── Telegram ─────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = _str("TELEGRAM_BOT_TOKEN")
TELEGRAM_OWNER_ID = _int("TELEGRAM_OWNER_ID", 0)          # твой числовой ID (узнать: команда /id)
TELEGRAM_ALLOWED_IDS = _id_list("TELEGRAM_ALLOWED_IDS")   # друзья: могут болтать, но без доступа к ПК
TELEGRAM_PUBLIC = _bool("TELEGRAM_PUBLIC", False)         # True — отвечать вообще всем (без доступа к ПК)
TELEGRAM_REPLY_MODE = _str("TELEGRAM_REPLY_MODE", "video").lower()  # video | voice | text
TELEGRAM_TEXT_WITH_MEDIA = _bool("TELEGRAM_TEXT_WITH_MEDIA", True)
TELEGRAM_VIDEO_SIZE = _int("TELEGRAM_VIDEO_SIZE", 384)
DESKTOP_SPEAKS_TELEGRAM = _bool("DESKTOP_SPEAKS_TELEGRAM", False)

# ─── Twitch (необязательно) ───────────────────────────────────
TWITCH_CHANNEL = _str("TWITCH_CHANNEL")
TWITCH_BOT_NICK = _str("TWITCH_BOT_NICK", "justinfan12345")
TWITCH_OAUTH_TOKEN = _str("TWITCH_OAUTH_TOKEN")
TWITCH_CHAT_INTERVAL = _float("TWITCH_CHAT_INTERVAL", 8.0)
