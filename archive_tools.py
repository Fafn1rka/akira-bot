"""
Приём zip-архивов — пришли Акире .zip (например, в Telegram), и она сможет рассказать, что
внутри, и ответить на вопросы по содержимому (включая код).

Каждый архив распаковывается в СВОЮ, новую, изолированную подпапку внутри data/archives/ —
никогда не поверх существующих файлов и никогда за пределами этой папки. Перед распаковкой
архив проверяется:
  • пути внутри не должны вести наружу (защита от перезаписи чужих файлов через "../../..");
  • размер в распакованном виде ограничен (защита от "zip-бомбы" — крошечного файла,
    который разворачивается в гигабайты и забивает диск).
Это ТОЛЬКО чтение: сама Акира ничего из архива не запускает и не копирует наружу.
"""
from __future__ import annotations

import io
import logging
import time
import zipfile
from pathlib import Path
from typing import Optional

import config

log = logging.getLogger("akira.archive")

ARCHIVES_DIR = config.DATA_DIR / "archives"
MAX_UNCOMPRESSED = 200 * 1024 * 1024    # 200 МБ в распакованном виде — дальше похоже на zip-бомбу
MAX_FILES = 5000
MAX_LIST = 200
MAX_READ_CHARS = 6000


class ArchiveError(Exception):
    """Архив не распакован. Текст — понятная причина для пользователя."""


def _safe_member(name: str) -> bool:
    """False — подозрительный путь (абсолютный или выходящий наружу через "..")."""
    p = Path(name)
    return not p.is_absolute() and ".." not in p.parts


def extract(data: bytes, label: str = "архив") -> Path:
    """Распаковывает в НОВУЮ изолированную подпапку data/archives/<...>/, возвращает её путь.
    Бросает ArchiveError, если архив битый, слишком большой или содержит подозрительные пути."""
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    slug = "".join(c for c in label if c.isalnum() or c in "-_")[:30] or "архив"
    dest = ARCHIVES_DIR / f"{int(time.time())}_{slug}"
    dest.mkdir(parents=True, exist_ok=False)

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ArchiveError("Это не похоже на рабочий zip-архив.") from e

    infos = zf.infolist()
    if len(infos) > MAX_FILES:
        raise ArchiveError(f"В архиве слишком много файлов ({len(infos)}) — не распаковываю.")
    total = sum(i.file_size for i in infos)
    if total > MAX_UNCOMPRESSED:
        mb = MAX_UNCOMPRESSED // 1024 // 1024
        raise ArchiveError(f"Архив в распакованном виде весил бы больше {mb} МБ — похоже на "
                          "«zip-бомбу», не распаковываю.")
    for info in infos:
        if not _safe_member(info.filename):
            raise ArchiveError(f"В архиве подозрительный путь «{info.filename}» — не распаковываю.")

    try:
        zf.extractall(dest)
    except OSError as e:
        raise ArchiveError(f"Не удалось распаковать: {e}") from e
    return dest


def describe(root: Path) -> str:
    """Список файлов внутри — что отвечать на «что там в архиве»."""
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    if not files:
        return "Архив пустой."
    lines = files[:MAX_LIST]
    extra = f"\n…и ещё {len(files) - MAX_LIST}" if len(files) > MAX_LIST else ""
    return f"В архиве {len(files)} файл(ов):\n" + "\n".join(lines) + extra


def read_file(root: Path, rel_path: str) -> str:
    """Читает один файл из распакованного архива (вопросы вроде «что в этом файле / коде»)."""
    try:
        target = (root / rel_path).resolve()
        target.relative_to(root.resolve())
    except (ValueError, OSError):
        return "Такой путь выходит за пределы архива — не читаю."
    if not target.is_file():
        return f"Файл «{rel_path}» не найден в архиве."
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Не удалось прочитать: {e}"
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n…(обрезано, файл большой)"
    return text


def find_root(hint: str) -> Optional[Path]:
    """По обрывку пути/названия находит нужную распакованную папку в data/archives/
    (чтобы в разговоре не нужно было помнить и повторять длинный путь целиком)."""
    if not ARCHIVES_DIR.is_dir():
        return None
    hint = (hint or "").strip()
    candidates = sorted((p for p in ARCHIVES_DIR.iterdir() if p.is_dir()),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not hint:
        return candidates[0] if candidates else None
    direct = ARCHIVES_DIR / hint
    if direct.is_dir():
        return direct
    for p in candidates:
        if hint.lower() in p.name.lower():
            return p
    return None
