"""Эмоции Акиры: метка [happy] в начале ответа модели + запасная эвристика."""
import re

VALID = {"neutral", "happy", "sad", "angry", "surprised", "thinking"}
TAG_RE = re.compile(r"^\s*\[(\w+)\]\s*")

EMOTION_PROMPT = (
    "\n\nКаждый ответ начинай с метки твоей эмоции в квадратных скобках: "
    "[neutral], [happy], [sad], [surprised], [angry] или [thinking]. "
    "Метка нужна для анимации аватара, пользователь её не увидит. "
    "Пример: [happy] Конечно, сейчас всё сделаю!"
)

_HINTS = {
    "happy": ("ура", "отлично", "рада", "здорово", "класс", "прекрасно", "😊", "😄", "ха-ха", "с радостью"),
    "sad": ("к сожалению", "жаль", "грустно", "прости", "извини", "увы"),
    "surprised": ("ого", "вау", "ничего себе", "неожиданно", "надо же"),
    "thinking": ("хм", "дай подумать", "посмотрим", "возможно,"),
    "angry": ("недопустимо", "возмутительно"),
}


def guess_emotion(text: str) -> str:
    low = text.lower()
    for emo, words in _HINTS.items():
        if any(w in low for w in words):
            return emo
    return "neutral"


def strip_tag(text: str):
    """(эмоция или None, текст без метки)"""
    m = TAG_RE.match(text)
    if m and m.group(1).lower() in VALID:
        return m.group(1).lower(), text[m.end():]
    return None, text


class EmotionFilter:
    """Потоковый фильтр: убирает метку из начала ответа и сообщает эмоцию."""

    def __init__(self, on_emotion=None):
        self.on_emotion = on_emotion
        self.emotion = None
        self.buf = ""
        self.done = False

    def _release(self) -> str:
        out, self.buf, self.done = self.buf, "", True
        return out

    def feed(self, tok: str) -> str:
        if self.done:
            return tok
        self.buf += tok
        s = self.buf.lstrip()
        if not s:
            return ""
        if not s.startswith("["):
            return self._release()
        end = s.find("]")
        if end == -1:
            return "" if len(s) <= 16 else self._release()
        tag = s[1:end].strip().lower()
        if tag in VALID:
            self.emotion = tag
            if self.on_emotion:
                self.on_emotion(tag)
            self.buf, self.done = "", True
            return s[end + 1:].lstrip()
        return self._release()

    def flush(self) -> str:
        return "" if self.done else self._release()
