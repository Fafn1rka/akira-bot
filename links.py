"""
Ссылки, которые Акира находит по твоим просьбам — на песню, на статью, на что угодно из
web_search. Каждая сохраняется, чтобы не искать заново (вкладка «Ссылки» в окне), а если
LINKS_NOTIFY=true (по умолчанию) — Акира сразу присылает её тебе в Telegram и Discord.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import config
from memory import JsonStore

MAX_LINKS = 300

_store: Optional[JsonStore] = None


def _s() -> JsonStore:
    global _store
    if _store is None:
        _store = JsonStore(config.DATA_DIR / "links.json")
        _store.data.setdefault("links", [])
    return _store


def add_link(url: str, title: str = "", kind: str = "инфо", source: str = "") -> dict:
    """Сохраняет ссылку (новые — сверху). Возвращает сохранённую запись."""
    if not url:
        return {}
    store = _s()
    entry = {"url": url, "title": title or url, "kind": kind, "source": source, "time": time.time()}
    items = store.data.setdefault("links", [])
    items.insert(0, entry)
    del items[MAX_LINKS:]
    store.save()
    return entry


def list_links(kind: Optional[str] = None, limit: int = 50) -> list[dict]:
    items = _s().data.get("links", [])
    if kind:
        items = [i for i in items if i.get("kind") == kind]
    return items[:limit]


def clear() -> None:
    _s().data["links"] = []
    _s().save()
