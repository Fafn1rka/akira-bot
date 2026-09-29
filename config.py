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


def parse_hhmm(spec: str) -> Tuple[int, int] | None:
    """'08:30' -> (8, 30); ошибка -> None."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", spec or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)), int(m.group(2))


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

# ─── AI ───────────────────────────────────────────────────────
# Gemini по-прежнему настраивается как раньше. Остальные провайдеры (OpenAI, Claude, Groq,
# OpenRouter, Ollama...) и несколько ключей/моделей — см. providers.py и .env.example:
# они читаются прямо из .env (GROQ_API_KEYS, OLLAMA_MODELS, AI_PROVIDERS и т.д.).
GEMINI_API_KEY = _str("GEMINI_API_KEY")
GEMINI_MODEL = _str("GEMINI_MODEL", "gemini-3.6-flash")

# ─── Дополнительные инструменты (время, напоминания, поиск в интернете, плеер) ──
ENABLE_EXTRA_TOOLS = _bool("ENABLE_EXTRA_TOOLS", True)

# ─── Взгляд на экран ──────────────────────────────────────────
# «Акира, посмотри на экран» — она делает скриншот и разбирает его (уходит выбранному AI, только по твоей просьбе).
ENABLE_SCREEN_VISION = _bool("ENABLE_SCREEN_VISION", True)
SCREEN_MONITOR = _int("SCREEN_MONITOR", 1)                      # 1 = основной монитор, 2 = второй, 0 = все сразу

# ─── Утренний брифинг ─────────────────────────────────────────
MORNING_BRIEFING = _bool("MORNING_BRIEFING", True)
BRIEFING_TIME = _str("BRIEFING_TIME", "08:30")                  # ЧЧ:ММ
BRIEFING_CITY = _str("BRIEFING_CITY")                           # для погоды; пусто = без погоды

# ─── Общая память владельца ───────────────────────────────────
# True — голос, Telegram и Discord помнят тебя ВМЕСТЕ (один разговор, одни и те же факты).
# False — у каждого канала связи своя отдельная память, как было раньше.
OWNER_KEY = "desktop:owner"
SHARED_OWNER_MEMORY = _bool("SHARED_OWNER_MEMORY", True)

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
VOICE_ENERGY_THRESHOLD = _float("VOICE_ENERGY_THRESHOLD", 0)   # 0 = подбирается сама под шум в комнате
VOICE_WAKE_WORD_REQUIRED = _bool("VOICE_WAKE_WORD_REQUIRED", True)
VOICE_CONVERSATION_WINDOW = _float("VOICE_CONVERSATION_WINDOW", 25)  # секунд без «Акира»
MIC_SAMPLE_RATE = 16000
VOICE_MIC_DEVICE = _str("VOICE_MIC_DEVICE")                     # номер или часть названия (список: test_mic.bat)
VOICE_INPUT_LANG = _str("VOICE_INPUT_LANG", "ru-RU")            # ru-RU | uk-UA | en-US | auto (только whisper)
WAKE_WORDS = tuple(w.strip().lower() for w in _str("WAKE_WORDS", "акира,акіра,akira").split(",") if w.strip())
# Чем распознавать речь: google (онлайн, без ключа), whisper (локально, точнее, работает без интернета)
# или auto — whisper, если установлен пакет faster-whisper, иначе google.
STT_ENGINE = _str("STT_ENGINE", "auto").lower()
WHISPER_MODEL = _str("WHISPER_MODEL", "small")                  # tiny | base | small | medium
WHISPER_DEVICE = _str("WHISPER_DEVICE", "cpu")                  # cpu | cuda (видеокарта NVIDIA)
WHISPER_COMPUTE = _str("WHISPER_COMPUTE", "int8")               # int8 для cpu, float16 для cuda
# Если интернета нет и edge-tts не сработал — озвучить встроенным голосом Windows
VOICE_OFFLINE_FALLBACK = _bool("VOICE_OFFLINE_FALLBACK", True)

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

# ─── Discord (необязательно) ──────────────────────────────────
DISCORD_BOT_TOKEN = _str("DISCORD_BOT_TOKEN")
DISCORD_OWNER_ID = _int("DISCORD_OWNER_ID", 0)                  # твой числовой ID в Discord
DISCORD_CHANNEL_IDS = _id_list("DISCORD_CHANNEL_IDS")           # каналы, где отвечать на всё
DISCORD_ALLOW_GUESTS = _bool("DISCORD_ALLOW_GUESTS", True)      # могут ли болтать не-владельцы
DISCORD_ALLOW_TERMINAL = _bool("DISCORD_ALLOW_TERMINAL", False) # консоль через Discord — ОПАСНО
DISCORD_GUEST_COOLDOWN = _float("DISCORD_GUEST_COOLDOWN", 3.0)  # сек между сообщениями одного гостя
DISCORD_VOICE_ALL = _bool("DISCORD_VOICE_ALL", False)           # озвучивать в голосовом канале ответы и гостям

# ─── Музыка ────────────────────────────────────────────────────
MUSIC_DIR = _str("MUSIC_DIR")                                    # пусто = папка «Музыка» пользователя
MUSIC_YOUTUBE_FALLBACK = _bool("MUSIC_YOUTUBE_FALLBACK", True)    # искать на YouTube, если своей музыки нет

SPOTIFY_CLIENT_ID = _str("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = _str("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = _str("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

# Присылать ли в Telegram/Discord ссылки, которые Акира сама находит (музыка, web_search)
LINKS_NOTIFY = _bool("LINKS_NOTIFY", True)
