"""
Данные для окна gui.py, вынесенные отдельно от Qt, чтобы их можно было проверить без запуска
графики: какие поля показывать в «Настройках» и как собрать сводку для вкладки «Статус».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Field:
    key: str                                 # имя переменной в .env
    label: str                               # подпись в окне
    kind: str = "text"                       # text | secret | bool | int
    hint: str = ""                           # маленькая подсказка под полем
    default: str = ""


SETTINGS_SCHEMA: list[tuple[str, list[Field]]] = [
    ("Общее", [
        Field("OWNER_NAME", "Как к тебе обращаться", default="Создатель"),
        Field("SHARED_OWNER_MEMORY", "Общая память во всех каналах связи", "bool", default="true"),
        Field("ENABLE_AVATAR", "Персонаж на рабочем столе", "bool", default="true"),
    ]),
    ("AI", [
        Field("GEMINI_API_KEY", "Ключ Gemini", "secret",
              hint="Бесплатно: aistudio.google.com/apikey"),
        Field("GEMINI_MODEL", "Модель Gemini", default="gemini-3.6-flash"),
        Field("OLLAMA_MODELS", "Модели Ollama (через запятую)",
              hint="Например: llama3.1 — должно совпадать с `ollama list`"),
        Field("AI_PROVIDERS", "Порядок провайдеров",
              hint="Например: gemini,ollama — пусто = по умолчанию"),
    ]),
    ("Голос", [
        Field("VOICE_INPUT_ENABLED", "Слушать микрофон", "bool", default="true"),
        Field("VOICE_ENERGY_THRESHOLD", "Порог громкости (0 = сама подберёт)", "int", default="0"),
        Field("VOICE_MIC_DEVICE", "Микрофон (номер или часть названия)"),
        Field("STT_ENGINE", "Распознавание речи (auto / google / whisper)", default="auto"),
    ]),
    ("Telegram", [
        Field("TELEGRAM_BOT_TOKEN", "Токен бота", "secret", hint="Получить: @BotFather -> /newbot"),
        Field("TELEGRAM_OWNER_ID", "Твой Telegram ID", "int"),
    ]),
    ("Discord", [
        Field("DISCORD_BOT_TOKEN", "Токен бота", "secret"),
        Field("DISCORD_OWNER_ID", "Твой Discord ID", "int"),
    ]),
    ("Музыка", [
        Field("MUSIC_DIR", "Папка с музыкой", hint="Пусто — папка «Музыка» пользователя"),
        Field("MUSIC_YOUTUBE_FALLBACK", "Искать на YouTube, если своей нет", "bool", default="true"),
        Field("SPOTIFY_CLIENT_ID", "Spotify: Client ID", "secret",
              hint="developer.spotify.com/dashboard, затем один раз spotify_login.bat"),
        Field("SPOTIFY_CLIENT_SECRET", "Spotify: Client Secret", "secret"),
        Field("LINKS_NOTIFY", "Присылать найденные ссылки в Telegram/Discord", "bool", default="true"),
    ]),
    ("Картинки", [
        Field("IMAGE_PROVIDER", "Кто рисует (auto / openai / gemini / pollinations)", default="auto",
              hint="auto — сама выберет по тому, какие ключи уже есть; pollinations работает без ключа"),
    ]),
    ("Брифинг и экран", [
        Field("MORNING_BRIEFING", "Утренний брифинг", "bool", default="true"),
        Field("BRIEFING_TIME", "Во сколько (ЧЧ:ММ)", default="08:30"),
        Field("BRIEFING_CITY", "Город для погоды"),
        Field("ENABLE_SCREEN_VISION", "Разрешить «посмотри на экран»", "bool", default="true"),
    ]),
]


def all_fields() -> list[Field]:
    return [f for _group, fields in SETTINGS_SCHEMA for f in fields]


def to_bool(value: str) -> bool:
    return (value or "").strip().lower() in ("true", "1", "yes", "on", "да")


def from_bool(value: bool) -> str:
    return "true" if value else "false"


# ------------------------------------------------------------------- статус
@dataclass
class StatusRow:
    label: str
    value: str
    ok: Optional[bool] = None            # True зелёный, False жёлтый/красный, None — нейтральный


def build_status(*, ai_summary: str, ai_connected: bool, mic_enabled: bool, mic_listening: bool,
                 telegram_configured: bool, telegram_running: bool,
                 discord_configured: bool, discord_running: bool,
                 avatar_running: bool, reminders_pending: int) -> list[StatusRow]:
    rows = [StatusRow("AI", ai_summary or "не настроен", ai_connected)]

    if not mic_enabled:
        rows.append(StatusRow("Микрофон", "выключен в настройках", None))
    else:
        rows.append(StatusRow("Микрофон", "слушает" if mic_listening else "не запустился", mic_listening))

    if telegram_configured:
        rows.append(StatusRow("Telegram", "подключён" if telegram_running else "не отвечает", telegram_running))
    else:
        rows.append(StatusRow("Telegram", "не настроен", None))

    if discord_configured:
        rows.append(StatusRow("Discord", "подключён" if discord_running else "не отвечает", discord_running))
    else:
        rows.append(StatusRow("Discord", "не настроен", None))

    rows.append(StatusRow("Персонаж на столе", "запущен" if avatar_running else "выключен", None))
    rows.append(StatusRow("Напоминания", f"{reminders_pending} ожидает" if reminders_pending else "нет активных", None))
    return rows
