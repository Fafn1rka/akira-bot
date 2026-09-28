"""
Утренний брифинг: в заданное время Акира сама здоровается и коротко рассказывает, какой сегодня
день, какая погода и какие у тебя напоминания на сегодня.

Настройки в .env:
    MORNING_BRIEFING=true       включить / выключить
    BRIEFING_TIME=08:30         во сколько (ЧЧ:ММ)
    BRIEFING_CITY=Berlin        город для погоды (пусто = без погоды)

Компьютер включили позже назначенного времени — поздороваемся сразу при запуске, но не позже чем
через 4 часа после него (вечером «доброе утро» ни к чему). Раз в день, повторно не будет.
Погода — бесплатный сервис Open-Meteo (https://open-meteo.com), ключ не нужен.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

import config

log = logging.getLogger("akira.briefing")

WINDOW_HOURS = 4
_TIMEOUT = 6

_WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
           "октября", "ноября", "декабря"]

# коды погоды WMO (их отдаёт Open-Meteo)
_WMO = {
    0: "ясно", 1: "почти ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь", 51: "лёгкая морось", 53: "морось", 55: "сильная морось",
    56: "ледяная морось", 57: "сильная ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "сильный ледяной дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа",
    80: "небольшие ливни", 81: "ливни", 82: "сильные ливни", 85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}


# ---------------------------------------------------------------- расписание
def is_due(now: datetime, at: tuple[int, int], last_date: Optional[str]) -> bool:
    """Пора ли здороваться: сегодня ещё не здоровалась, время наступило и окно не закрылось."""
    if last_date == now.date().isoformat():
        return False
    start = now.replace(hour=at[0], minute=at[1], second=0, microsecond=0)
    return start <= now < start + timedelta(hours=WINDOW_HOURS)


# ------------------------------------------------------------------- погода
def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "akira-bot"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310  (адрес — наш, https)
        return json.loads(r.read().decode("utf-8"))


def get_weather(city: str) -> Optional[str]:
    """'Berlin: сейчас 14°, пасмурно; днём от 9° до 15°, вероятность осадков 40%'. None — не получилось."""
    city = (city or "").strip()
    if not city:
        return None
    try:
        geo = _http_json("https://geocoding-api.open-meteo.com/v1/search?count=1&language=ru&name="
                         + urllib.parse.quote(city))
        found = (geo.get("results") or [])
        if not found:
            log.info("Погода: город «%s» не найден.", city)
            return None
        place = found[0]
        data = _http_json(
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={place['latitude']}&longitude={place['longitude']}"
            "&current=temperature_2m,weather_code"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            "&timezone=auto&forecast_days=1")
        cur = data.get("current") or {}
        day = data.get("daily") or {}
        parts = []
        if cur.get("temperature_2m") is not None:
            desc = _WMO.get(int(cur.get("weather_code", -1)), "")
            parts.append(f"сейчас {cur['temperature_2m']:.0f}°" + (f", {desc}" if desc else ""))
        tmin, tmax = (day.get("temperature_2m_min") or [None])[0], (day.get("temperature_2m_max") or [None])[0]
        if tmin is not None and tmax is not None:
            parts.append(f"днём от {tmin:.0f}° до {tmax:.0f}°")
        rain = (day.get("precipitation_probability_max") or [None])[0]
        if rain is not None:
            parts.append(f"вероятность осадков {rain:.0f}%")
        if not parts:
            return None
        return f"{place.get('name', city)}: " + "; ".join(parts)
    except Exception as e:  # noqa: BLE001  (нет интернета, сервис недоступен...)
        log.info("Погоду получить не удалось: %s", e)
        return None


# ----------------------------------------------------------------- сборка
def gather_facts(brain=None, city: Optional[str] = None, now: Optional[datetime] = None,
                 plain: bool = False) -> str:
    """Факты для приветствия одним текстом: дата, погода, напоминания на сегодня.
    plain=True — без подсказок для модели (для случая, когда AI недоступен и текст читается как есть)."""
    now = now or datetime.now()
    city = config.BRIEFING_CITY if city is None else city
    lines = [f"Сегодня {now.day} {_MONTHS[now.month - 1]}, {_WEEKDAYS[now.weekday()]}, сейчас {now:%H:%M}."]

    weather = get_weather(city) if city else None
    if weather:
        lines.append(f"Погода: {weather}.")
    elif not plain:
        lines.append("Город для погоды не указан (BRIEFING_CITY в .env), про погоду не говори." if not city
                     else "Погоду узнать не удалось, про неё не говори.")

    if brain is not None:
        try:
            today = [(due, text) for due, text in brain.pending_reminders()
                     if datetime.fromtimestamp(due).date() == now.date()]
        except Exception:  # noqa: BLE001
            today = []
        if today:
            items = ", ".join(f"в {datetime.fromtimestamp(d):%H:%M} — {t}" for d, t in today[:8])
            lines.append(f"Напоминания на сегодня: {items}.")
        else:
            lines.append("Напоминаний на сегодня нет.")
    return "\n".join(lines)


def build_prompt(owner: str, facts: str) -> str:
    """Задание для Акиры: превратить сухие факты в живое приветствие."""
    return (f"Сейчас утро — поздоровайся с {owner} по-своему, тепло и без пафоса. В 3–5 коротких "
            "предложениях скажи, какой сегодня день, и — если есть в данных — про погоду и про его "
            "напоминания на сегодня. Добавь короткое доброе пожелание на день. Используй ТОЛЬКО эти данные, "
            "ничего не выдумывай.\n\nДанные:\n" + facts)
