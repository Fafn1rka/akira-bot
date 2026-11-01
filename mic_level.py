"""
Текущая громкость с микрофона — для индикатора «доходит ли звук» в окне (вкладка «Статус»).

Записывается голосовым модулем (voice_listener.py) в простой файл, тем же приёмом, что и
avatar_state.py (атомарная запись через временный файл + переименование) — поэтому индикатор
видит уровень, даже если окно и голос работают в разных потоках или процессах.
"""
from __future__ import annotations

import json
import os
import time
from typing import Tuple

import config

_PATH = config.DATA_DIR / "mic_level.json"
STALE_AFTER = 2.0   # не обновлялось дольше — считаем, что микрофон сейчас не слушает


def write(level: float, threshold: float) -> None:
    try:
        tmp = _PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"level": round(float(level), 1), "threshold": round(float(threshold), 1),
                                   "ts": time.time()}), encoding="utf-8")
        os.replace(tmp, _PATH)
    except Exception:  # noqa: BLE001 — индикатор не должен ронять голосовой поток
        pass


def read() -> Tuple[float, float, bool]:
    """(текущий уровень, порог речи, свежие ли данные — слушает ли микрофон вообще сейчас)."""
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        fresh = time.time() - d.get("ts", 0) <= STALE_AFTER
        return float(d.get("level", 0.0)), float(d.get("threshold", 0.0)), fresh
    except Exception:  # noqa: BLE001
        return 0.0, 0.0, False
