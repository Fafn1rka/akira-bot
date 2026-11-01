"""
Угадывает настроение по тексту, который Акира собирается сказать — чтобы персонаж на рабочем
столе менялся в цвете и темпе анимации не только по тому, что она ДЕЛАЕТ (думает/говорит), но и
по тому, ЧТО она говорит: весело, грустно, взволнованно...

Специально не отдельный запрос к AI — настроение определяется на месте, без задержки и без
лишних затрат, по ключевым словам и знакам препинания. Поэтому результат предсказуем и
проверяем — это не "мнение модели", а простое и прозрачное правило.
"""
from __future__ import annotations

import re

NEUTRAL, HAPPY, SAD, EXCITED, SURPRISED, LOVING = (
    "neutral", "happy", "sad", "excited", "surprised", "loving")
MOODS = (NEUTRAL, HAPPY, SAD, EXCITED, SURPRISED, LOVING)

# Порядок важен: первое совпадение побеждает, более "сильные" эмоции — выше.
_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (SURPRISED, re.compile(r"\b(ого|оо|вот это да|не может быть|серьёзно\?|правда\?|ничего себе|"
                           r"ух ты|whoa|no way)\b", re.IGNORECASE)),
    (LOVING, re.compile(r"(люблю тебя|обожаю тебя|скуч(аю|ала) по тебе|ты лучш[а-я]*|"
                        r"❤|💕|🥰|😍)", re.IGNORECASE)),
    (SAD, re.compile(r"\b(жаль|грустно|соболезн|сочувств|не получилось|прости(те)?|сожале|"
                     r"печаль|увы|к сожалению)\b|😢|😔|💔", re.IGNORECASE)),
    (EXCITED, re.compile(r"(ура+!|вперёд!|давай!|погнали|класс!!|супер!!|обожаю это|"
                         r"!!!|🎉|🔥|⚡)", re.IGNORECASE)),
    (HAPPY, re.compile(r"\b(рада|здорово|отлично|прекрасно|замечательно|чудесно|хорошая новость|"
                       r"повезло|весело)\b|😊|😄|🙂|❤️", re.IGNORECASE)),
)


def detect(text: str) -> str:
    """Текст ответа -> одно из MOODS. Пустой/непонятный текст -> neutral."""
    text = (text or "").strip()
    if not text:
        return NEUTRAL
    for mood, pattern in _RULES:
        if pattern.search(text):
            return mood
    return NEUTRAL
