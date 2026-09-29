"""
«Меню» — твои собственные кнопки быстрых действий в окне Акиры: включить любимую песню, открыть
сайт, запустить сценарий или отправить Акире готовую фразу. Настраивается прямо в окне, во
вкладке «Меню» (Добавить / Изменить / Удалить) — хранится в data/quickmenu.json, правится и
руками (обычным текстом), если так удобнее.
"""
from __future__ import annotations

from typing import Optional

import config
from memory import JsonStore

# music — включить трек/исполнителя (как play_music); url — открыть ссылку в браузере;
# scene — включить сценарий (как в разделе «Сценарии»); chat — отправить Акире готовую фразу.
ACTIONS: tuple[str, ...] = ("music", "url", "scene", "chat")

DEFAULT_ITEMS: list[dict] = [
    {"label": "Рабочий режим", "action": "scene", "value": "рабочий режим"},
    {"label": "Статус компьютера", "action": "chat", "value": "как там компьютер?"},
]

_store: Optional[JsonStore] = None


def _s() -> JsonStore:
    global _store
    if _store is None:
        _store = JsonStore(config.DATA_DIR / "quickmenu.json")
        if "items" not in _store.data:
            _store.data["items"] = [dict(i) for i in DEFAULT_ITEMS]
            _store.save()
    return _store


def list_items() -> list[dict]:
    return list(_s().data.get("items", []))


def save_items(items: list[dict]) -> None:
    _s().data["items"] = items
    _s().save()


def add_item(label: str, action: str, value: str) -> None:
    items = list_items()
    items.append({"label": label, "action": action, "value": value})
    save_items(items)


def update_item(index: int, label: str, action: str, value: str) -> bool:
    items = list_items()
    if not (0 <= index < len(items)):
        return False
    items[index] = {"label": label, "action": action, "value": value}
    save_items(items)
    return True


def remove_item(index: int) -> bool:
    items = list_items()
    if not (0 <= index < len(items)):
        return False
    del items[index]
    save_items(items)
    return True
