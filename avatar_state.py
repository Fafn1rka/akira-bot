"""
Малюсенькая «шина» между основным процессом (бот) и процессом окна-персонажа
(avatar.py). Состояние — это буквально пара значений (state, level), поэтому
проще и надёжнее держать их в маленьком файле, чем поднимать сокеты: работает
одинаково на Windows и Linux, не требует открытых портов.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Tuple

import config

_PATH = config.DATA_DIR / "avatar_state.json"
_POS_PATH = config.DATA_DIR / "avatar_pos.json"

STALE_AFTER = 1.2  # секунд: если бот перестал писать состояние — считаем, что она молчит


def write_state(state: str, level: float = 0.0) -> None:
    try:
        tmp = _PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"state": state, "level": round(float(level), 3), "ts": time.time()}),
                       encoding="utf-8")
        os.replace(tmp, _PATH)
    except Exception:  # noqa: BLE001 — анимация не должна валить бота
        pass


def read_state() -> Tuple[str, float]:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        if time.time() - d.get("ts", 0) > STALE_AFTER:
            return "idle", 0.0
        return d.get("state", "idle"), float(d.get("level", 0.0))
    except Exception:  # noqa: BLE001
        return "idle", 0.0


def save_position(x: int, y: int) -> None:
    try:
        _POS_PATH.write_text(json.dumps({"x": x, "y": y}), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def load_position() -> Tuple[int, int] | None:
    try:
        d = json.loads(_POS_PATH.read_text(encoding="utf-8"))
        return int(d["x"]), int(d["y"])
    except Exception:  # noqa: BLE001
        return None
