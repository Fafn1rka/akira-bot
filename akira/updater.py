"""Обновления: manifest.json -> загрузка zip -> проверка SHA-256 -> резервная копия -> установка (с откатом)."""
import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import requests

SKIP_ALWAYS = ("config.toml", "persona.md", "skills/skills.lock")           # ваши файлы: не трогаем
SKIP_PREFIXES = ("data/", "assets/", "backups/", "web/vendor/", ".venv/", "__pycache__/")
MAX_ZIP = 100 * 1024 * 1024


class UpdateError(Exception):
    pass


def parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except ValueError as e:
        raise UpdateError(f"некорректная версия: {v!r}") from e


def _require_https(url: str, allow_insecure: bool):
    if not url.startswith("https://") and not allow_insecure:
        raise UpdateError("обновления разрешены только по https")


def check(url: str, current: str, allow_insecure=False) -> dict | None:
    """Возвращает manifest, если есть новая версия, иначе None."""
    _require_https(url, allow_insecure)
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        m = r.json()
    except (requests.RequestException, ValueError) as e:
        raise UpdateError(f"не удалось получить manifest: {e}") from e
    for k in ("version", "url", "sha256"):
        if k not in m:
            raise UpdateError(f"в manifest нет поля {k}")
    return m if parse_version(m["version"]) > parse_version(current) else None


def _skipped(rel: str, exists: bool) -> bool:
    if rel in SKIP_ALWAYS:
        return exists                       # первый раз можно положить, перезаписывать - нет
    return rel.startswith(SKIP_PREFIXES) and exists


def _backup(base: Path, version: str) -> Path:
    out = base / "backups"
    out.mkdir(exist_ok=True)
    dest = out / f"akira-{version}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in base.rglob("*"):
            rel = f.relative_to(base).as_posix()
            if f.is_file() and not rel.startswith(SKIP_PREFIXES) and "__pycache__" not in rel:
                z.write(f, rel)
    return dest


def _safe_extract(z: zipfile.ZipFile, dest: Path):
    root = dest.resolve()
    for name in z.namelist():
        if not (dest / name).resolve().is_relative_to(root):
            raise UpdateError("в архиве небезопасный путь (zip-slip)")
    z.extractall(dest)


def apply(base: Path, manifest: dict, current: str, allow_insecure=False) -> str:
    _require_https(manifest["url"], allow_insecure)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zpath = tmp / "update.zip"
        h, size = hashlib.sha256(), 0
        try:
            with requests.get(manifest["url"], stream=True, timeout=30) as r, open(zpath, "wb") as f:
                r.raise_for_status()
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_ZIP:
                        raise UpdateError("архив слишком большой")
                    h.update(chunk)
                    f.write(chunk)
        except requests.RequestException as e:
            raise UpdateError(f"загрузка не удалась: {e}") from e
        if h.hexdigest().lower() != str(manifest["sha256"]).lower():
            raise UpdateError("SHA-256 не совпал - файл повреждён или подменён, установка отменена")
        ex = tmp / "x"
        with zipfile.ZipFile(zpath) as z:
            _safe_extract(z, ex)
        roots = [p.parent for p in ex.rglob("VERSION") if (p.parent / "akira" / "__init__.py").exists()]
        if not roots:
            raise UpdateError("в архиве не найден проект Акиры")
        src = roots[0]
        new_v = (src / "VERSION").read_text(encoding="utf-8").strip()
        if new_v != manifest["version"] or parse_version(new_v) <= parse_version(current):
            raise UpdateError(f"версия в архиве ({new_v}) не соответствует manifest или не новее текущей")

        backup = _backup(base, current)
        try:
            for f in src.rglob("*"):
                if not f.is_file() or "__pycache__" in f.parts:
                    continue
                rel = f.relative_to(src).as_posix()
                dest = base / rel
                if _skipped(rel, dest.exists()):
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
        except Exception as e:  # noqa: BLE001
            _restore(base, backup)
            raise UpdateError(f"сбой при установке, выполнен откат: {e}") from e
    return f"Обновлено до {manifest['version']}. Резервная копия: {backup.name}"


def _restore(base: Path, backup: Path):
    with zipfile.ZipFile(backup) as z:
        _safe_extract(z, base)


def rollback(base: Path) -> str:
    backups = sorted((base / "backups").glob("akira-*.zip"))
    if not backups:
        raise UpdateError("резервных копий нет")
    _restore(base, backups[-1])
    return f"Восстановлено из {backups[-1].name}"
