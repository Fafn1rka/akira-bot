import tomllib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: Path | None = None) -> dict:
    """config.default.toml (обновляется) + config.toml (ваши правки) поверх него."""
    cfg = {}
    for p in (BASE_DIR / "config.default.toml", path or BASE_DIR / "config.toml"):
        if p.exists():
            with open(p, "rb") as f:
                cfg = _merge(cfg, tomllib.load(f))
    return cfg


def load_persona() -> str:
    p = BASE_DIR / "persona.md"
    return p.read_text(encoding="utf-8").strip() if p.exists() else "Ты - Акира, ИИ-ассистент."


def version() -> str:
    v = BASE_DIR / "VERSION"
    return v.read_text(encoding="utf-8").strip() if v.exists() else "0"
