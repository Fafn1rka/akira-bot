import json
import math
import sqlite3
import threading
import time
from pathlib import Path


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Memory:
    """Долгая память: история диалога + факты с семантическим поиском (SQLite). Потокобезопасна."""

    def __init__(self, db_path: Path, embed_fn=None):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.RLock()
        self.embed_fn = embed_fn  # функция text -> list[float] или None
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY, ts REAL, role TEXT, content TEXT);
                CREATE TABLE IF NOT EXISTS facts(
                    id INTEGER PRIMARY KEY, ts REAL, text TEXT, embedding TEXT);
                """
            )
            self.db.commit()

    # --- история ---
    def add_message(self, role: str, content: str):
        with self._lock:
            self.db.execute("INSERT INTO messages(ts, role, content) VALUES(?,?,?)", (time.time(), role, content))
            self.db.commit()

    def recent_messages(self, n: int) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    # --- факты ---
    def add_fact(self, text: str) -> int:
        text = text.strip()
        emb = None
        if self.embed_fn:
            try:
                emb = json.dumps(self.embed_fn(text))
            except Exception:
                emb = None
        with self._lock:
            cur = self.db.execute("INSERT INTO facts(ts, text, embedding) VALUES(?,?,?)", (time.time(), text, emb))
            self.db.commit()
            return cur.lastrowid

    def list_facts(self) -> list[tuple[int, str]]:
        with self._lock:
            return self.db.execute("SELECT id, text FROM facts ORDER BY id").fetchall()

    def delete_fact(self, fact_id: int) -> bool:
        with self._lock:
            cur = self.db.execute("DELETE FROM facts WHERE id=?", (fact_id,))
            self.db.commit()
            return cur.rowcount > 0

    def recall(self, query: str, top_k=5, min_score=0.55) -> list[str]:
        with self._lock:
            rows = self.db.execute("SELECT id, text, embedding FROM facts").fetchall()
        if not rows:
            return []
        qv = None
        if self.embed_fn:
            try:
                qv = self.embed_fn(query)
            except Exception:
                qv = None
        if qv is None:  # запасной вариант: последние факты
            return [t for _, t, _ in rows[-top_k:]]
        scored = []
        for _, text, emb in rows:
            if emb:
                scored.append((_cosine(qv, json.loads(emb)), text))
        scored.sort(reverse=True)
        return [t for s, t in scored[:top_k] if s >= min_score]
