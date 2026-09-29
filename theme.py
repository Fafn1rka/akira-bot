"""
Оформление окна Акиры: готовые цветовые темы и размер шрифта. Применяется сразу, без
перезапуска Акиры (в отличие от остальных настроек) — это только про то, как выглядит ОКНО.
"""
from __future__ import annotations

from typing import Optional

import config
from memory import JsonStore

PRESETS: dict[str, dict[str, str]] = {
    "Тёмная (по умолчанию)": {"bg": "#1e1e24", "panel": "#2a2a33", "text": "#e8e8ec", "accent": "#8b7fd6"},
    "Светлая":               {"bg": "#f5f5f7", "panel": "#ffffff", "text": "#1c1c1e", "accent": "#6a5acd"},
    "Тёплая":                {"bg": "#221a14", "panel": "#2c2018", "text": "#f0e6da", "accent": "#d8a05a"},
    "Ледяная":                {"bg": "#101820", "panel": "#16222c", "text": "#dbeeff", "accent": "#4fc3f7"},
    "Розовая":                {"bg": "#1f1520", "panel": "#2a1c2c", "text": "#f3e4ee", "accent": "#e88fc2"},
}
DEFAULT_PRESET = "Тёмная (по умолчанию)"
FONT_SIZES: tuple[int, ...] = (10, 11, 12, 13, 14, 16, 18, 20)
DEFAULT_FONT_SIZE = 12

_store: Optional[JsonStore] = None


def _s() -> JsonStore:
    global _store
    if _store is None:
        _store = JsonStore(config.DATA_DIR / "theme.json")
    return _store


def load() -> dict:
    d = _s().data
    preset = d.get("preset")
    size = d.get("font_size")
    return {
        "preset": preset if preset in PRESETS else DEFAULT_PRESET,
        "font_size": size if size in FONT_SIZES else DEFAULT_FONT_SIZE,
    }


def save(preset: str, font_size: int) -> None:
    store = _s()
    store.data["preset"] = preset if preset in PRESETS else DEFAULT_PRESET
    store.data["font_size"] = font_size if font_size in FONT_SIZES else DEFAULT_FONT_SIZE
    store.save()


def stylesheet(preset: str, font_size: int) -> str:
    p = PRESETS.get(preset, PRESETS[DEFAULT_PRESET])
    size = font_size if font_size in FONT_SIZES else DEFAULT_FONT_SIZE
    return f"""
        QWidget {{ background-color: {p['bg']}; color: {p['text']}; font-size: {size}px; }}
        QTabWidget::pane {{ border: 1px solid {p['panel']}; }}
        QTabBar::tab {{ background: {p['panel']}; color: {p['text']}; padding: 6px 14px; }}
        QTabBar::tab:selected {{ background: {p['accent']}; color: #ffffff; }}
        QPushButton {{ background: {p['accent']}; color: #ffffff; border: none;
                       padding: 6px 14px; border-radius: 5px; }}
        QPushButton:disabled {{ background: {p['panel']}; color: #888888; }}
        QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QComboBox {{
            background: {p['panel']}; color: {p['text']};
            border: 1px solid {p['accent']}; border-radius: 4px; padding: 3px;
        }}
        QScrollArea {{ border: none; }}
    """
