"""Навыки (плагины): skills/<имя>/skill.py. Включаются явно, код закреплён SHA-256 - изменённый навык не загрузится."""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


class SkillAPI:
    """Всё, что навык получает от Акиры."""

    def __init__(self, name, toolbox, hub, workspace: Path, settings: dict):
        self.name, self._tb, self._hub = name, toolbox, hub
        self.workspace, self.settings = workspace, settings

    def tool(self, name, description, props=None, required=None, risk="confirm", describe=None):
        """Декоратор регистрации инструмента. risk: 'safe' или 'confirm' (по умолчанию - спрашивать)."""
        if risk not in ("safe", "confirm"):
            raise ValueError("risk должен быть 'safe' или 'confirm'")
        full = f"{self.name}_{name}"

        def deco(fn):
            self._tb._add(full, description, props or {}, required or [], risk, fn,
                          describe or (lambda a, n=full: f"Навык {n}: {a}"), group="skill")
            return fn
        return deco

    def keywords(self, *words):
        self._tb.keywords.extend(w.lower() for w in words)

    def notify(self, text: str):
        if self._hub:
            self._hub.notify(text)


class SkillManager:
    def __init__(self, base_dir: Path, toolbox, hub, cfg: dict):
        self.dir = base_dir / "skills"
        self.lock_path = self.dir / "skills.lock"
        self.tb, self.hub, self.cfg = toolbox, hub, cfg
        self.dir.mkdir(exist_ok=True)

    # --- учёт и целостность ---
    def available(self) -> list[str]:
        return sorted(p.parent.name for p in self.dir.glob("*/skill.py") if NAME_RE.match(p.parent.name))

    def _lock(self) -> dict:
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict):
        self.lock_path.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")

    def digest(self, name: str) -> str:
        h = hashlib.sha256()
        for f in sorted((self.dir / name).rglob("*.py")):
            h.update(str(f.relative_to(self.dir / name)).encode())
            h.update(f.read_bytes())
        return h.hexdigest()

    def enable(self, name: str):
        if name not in self.available():
            raise ValueError(f"навык {name} не найден в skills/")
        lock = self._lock()
        lock[name] = self.digest(name)
        self._save(lock)

    def disable(self, name: str):
        lock = self._lock()
        lock.pop(name, None)
        self._save(lock)

    def status(self) -> list[tuple[str, str]]:
        out = []
        for name, digest in self._lock().items():
            if name not in self.available():
                out.append((name, "файлы навыка не найдены"))
            elif self.digest(name) != digest:
                out.append((name, "КОД ИЗМЕНЁН после утверждения - не загружен, проверьте и включите заново"))
            else:
                out.append((name, "ok"))
        return out

    # --- загрузка ---
    def load_all(self) -> list[str]:
        loaded = []
        for name, status in self.status():
            if status != "ok":
                print(f"  [!] Навык {name}: {status}")
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"akira_skill_{name}", self.dir / name / "skill.py")
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                settings = self.cfg.get("skills", {}).get("config", {}).get(name, {})
                before = len(self.tb.tools)
                mod.register(SkillAPI(name, self.tb, self.hub, self.tb.workspace, settings))
                loaded.append(f"{name} (+{len(self.tb.tools) - before})")
            except Exception as e:  # noqa: BLE001 - сбой одного навыка не должен ронять Акиру
                print(f"  [!] Навык {name} не загрузился: {type(e).__name__}: {e}")
        return loaded
