"""
Буфер обмена владельца — «что я только что скопировал». Через пакет pyperclip, который сам
умеет работать и на Windows, и на Linux (там ему только нужна системная программа xclip/xsel —
обычно она уже стоит, а если нет, ставится одной командой, см. сообщение об ошибке ниже).
"""
from __future__ import annotations

MAX_CHARS = 4000


def read() -> str:
    try:
        import pyperclip
    except ImportError:
        return "Не установлен пакет pyperclip: pip install pyperclip"
    try:
        text = pyperclip.paste()
    except Exception as e:  # noqa: BLE001  (на Linux без xclip/xsel/wl-clipboard pyperclip тут падает)
        return (f"Не удалось прочитать буфер обмена ({type(e).__name__}). "
                "На Linux для этого нужна программа xclip: sudo apt install xclip")
    if not text or not text.strip():
        return "В буфере обмена сейчас пусто."
    text = text.strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n…(в буфере было больше, показана часть)"
    return text
