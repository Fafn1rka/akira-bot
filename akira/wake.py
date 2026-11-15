"""Слово активации «Акира» и голосовые команды управления."""
import re
from difflib import SequenceMatcher

WAKE_WORDS = ("акира", "akira")
STOP_WORDS = {"хватит", "стоп", "отбой", "пока", "отмена", "свободна"}
EXIT_WORDS = {"выключись", "выключайся"}
PUNCT = " ,.!?-—:;\"'«»"


def find_wake(text: str):
    """Возвращает (услышали ли имя, остаток фразы-команда)."""
    low = text.lower()
    for m in re.finditer(r"[\w-]+", low):
        w = m.group(0)
        if max(SequenceMatcher(None, w, k).ratio() for k in WAKE_WORDS) >= 0.78:
            after, before = text[m.end():], text[:m.start()]
            return True, (after.strip(PUNCT) or before.strip(PUNCT))
    return False, text.strip(PUNCT)


def _words(text: str):
    return re.findall(r"[\w-]+", text.lower())


def is_stop(text: str) -> bool:
    w = _words(text)
    return 0 < len(w) <= 3 and any(x in STOP_WORDS for x in w)


def is_exit(text: str) -> bool:
    w = _words(text)
    return 0 < len(w) <= 3 and any(x in EXIT_WORDS for x in w)
