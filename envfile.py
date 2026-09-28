"""
Точечное чтение и правка файла .env. Используется окном настроек (gui.py), но написано
без зависимости от Qt, поэтому его можно проверить и использовать отдельно.

apply() меняет ТОЛЬКО те строки, что переданы в changes: остальной файл (комментарии, порядок,
пустые строки) остаётся как есть. Если строка была закомментирована (# ключ=...), она включается.
Если ключа в файле совсем нет — дописывается в конец, под отдельным заголовком (один раз).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

_NEW_HEADER = "# ── Добавлено через окно настроек ──────────────────────────────"


def read(path: Path) -> dict[str, str]:
    """Все ключи файла, включая закомментированные (без запуска Python — просто разбор текста)."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        body = line[1:].strip() if line.startswith("#") else line
        if "=" in body and re.match(r"^[A-Z][A-Z0-9_]*=", body):
            k, v = body.split("=", 1)
            if k not in out or not line.startswith("#"):   # включённая строка важнее закомментированной
                out[k.strip()] = v.strip().strip("'\"")
    return out


def apply(path: Path, changes: dict[str, str], backup: bool = True) -> None:
    """Записывает changes в файл. Значение "" не удаляет строку — просто ставит пустое значение
    (так безопаснее: случайно не потерять чужую настройку)."""
    if not changes:
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    remaining = dict(changes)

    for i, raw in enumerate(lines):
        line = raw.strip()
        body = line[1:].strip() if line.startswith("#") else line
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", body)
        if not m or m.group(1) not in remaining:
            continue
        key = m.group(1)
        lines[i] = f"{key}={remaining.pop(key)}"

    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        if _NEW_HEADER not in lines:
            lines.append(_NEW_HEADER)
        for key, value in remaining.items():
            lines.append(f"{key}={value}")

    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
