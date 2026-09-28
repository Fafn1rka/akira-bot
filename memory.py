"""
Память Акиры на диске (папка data/):
  memory.json — история разговоров и «факты о тебе» (переживает перезапуск и перезагрузку ПК)
  prefs.json  — настройки чатов Telegram (режим ответов, «писать первой»)
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import config

MAX_STORED_TURNS = 80


class JsonStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        with self._lock:
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(self.data, dict):
                    self.data = {}
            except FileNotFoundError:
                self.data = {}
            except Exception:  # noqa: BLE001 — битый файл: сохраняем копию и начинаем заново
                try:
                    self.path.replace(self.path.with_suffix(".broken.json"))
                except Exception:  # noqa: BLE001
                    pass
                self.data = {}

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)  # атомарно: файл не испортится при отключении питания


class Memory(JsonStore):
    def __init__(self, path: Path | None = None):
        super().__init__(path or config.DATA_DIR / "memory.json")
        self.data.setdefault("sessions", {})

    def session(self, key: str) -> Dict[str, Any]:
        with self._lock:
            return self.data["sessions"].setdefault(key, {"turns": [], "facts": [], "name": ""})

    def turns(self, key: str) -> List[dict]:
        return list(self.session(key)["turns"])

    def facts(self, key: str) -> List[str]:
        return list(self.session(key)["facts"])

    def add_turn(self, key: str, role: str, text: str) -> None:
        with self._lock:
            s = self.session(key)
            s["turns"].append({"role": role, "text": text, "ts": int(time.time())})
            if len(s["turns"]) > MAX_STORED_TURNS:
                del s["turns"][: len(s["turns"]) - MAX_STORED_TURNS]
            self.save()

    def add_fact(self, key: str, fact: str) -> bool:
        fact = fact.strip()[:300]
        if not fact:
            return False
        with self._lock:
            s = self.session(key)
            if fact.lower() in (f.lower() for f in s["facts"]):
                return True
            s["facts"].append(fact)
            del s["facts"][:-60]
            self.save()
            return True

    def merge_facts(self, src: str, dst: str) -> int:
        """Переносит факты из src в dst (без дублей) и очищает их в src.
        Нужно, чтобы владелец в Telegram/Discord и за компьютером стал одним человеком."""
        with self._lock:
            if src == dst or src not in self.data["sessions"]:
                return 0
            facts = list(self.session(src)["facts"])
            if not facts:
                return 0
            for f in facts:
                self.add_fact(dst, f)
            self.session(src)["facts"] = []
            self.save()
            return len(facts)

    def clear(self, key: str, facts_too: bool = True) -> None:
        with self._lock:
            s = self.session(key)
            s["turns"] = []
            if facts_too:
                s["facts"] = []
            self.save()


class Prefs(JsonStore):
    def __init__(self, path: Path | None = None):
        super().__init__(path or config.DATA_DIR / "prefs.json")

    def get(self, chat_id: int, name: str, default: Any = None) -> Any:
        with self._lock:
            return self.data.get(str(chat_id), {}).get(name, default)

    def set(self, chat_id: int, name: str, value: Any) -> None:
        with self._lock:
            self.data.setdefault(str(chat_id), {})[name] = value
            self.save()
