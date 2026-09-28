"""
Своя музыка: «Акира, включи <песню/исполнителя>» — ищет в твоей папке с музыкой и включает,
а если не нашла — ищет на YouTube и открывает там. Дальше пауза/следующий/предыдущий — уже
знакомые команды через mediakeys.py (они работают с любым плеером, который открылся).

Ставить свой плеер не нужно: локальный файл открывается тем плеером, что у тебя назначен
по умолчанию для музыки (Windows сама решает — это может быть штатное приложение, foobar2000,
VLC и т.д.), а YouTube — в браузере.

Настройки в .env:
    MUSIC_DIR=C:\\Users\\ты\\Music     папка с музыкой (по умолчанию — папка «Музыка» пользователя)
    MUSIC_YOUTUBE_FALLBACK=true      искать на YouTube, если в папке ничего не нашлось

Точность тегов (кто исполнитель, как называется трек) лучше с пакетом mutagen — необязательно,
без него используются только имена файлов. Поиск на YouTube — через yt-dlp, тоже необязательно
и без ключей API.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import config

log = logging.getLogger("akira.music")

AUDIO_EXT = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus", ".aac", ".wma"}
MAX_FILES = 20_000            # защита от случайно указанной огромной/системной папки
RESCAN_SECONDS = 300           # пересканировать папку не чаще раза в 5 минут

_TRACK_PREFIX = re.compile(r"^\s*(\d{1,3})[\s._\-)]+")           # "03 - " / "03. " в начале имени файла
_JUNK = re.compile(r"[\[\(][^\])]*[\]\)]")                       # "(Official Video)", "[Remastered 2011]"


@dataclass
class Track:
    path: Path
    title: str
    artist: str = ""

    @property
    def display(self) -> str:
        return f"{self.artist} — {self.title}" if self.artist else self.title

    @property
    def search_text(self) -> str:
        return f"{self.artist} {self.title} {self.path.stem}".lower()


_cache: dict[str, tuple[float, list[Track]]] = {}


def music_dir() -> Path:
    custom = getattr(config, "MUSIC_DIR", "") or os.getenv("MUSIC_DIR", "")
    if custom:
        return Path(custom).expanduser()
    home = Path.home()
    for name in ("Music", "Музыка"):                              # у локализованной Windows папка называется иначе
        if (home / name).is_dir():
            return home / name
    return home / "Music"


def _clean_title(stem: str) -> str:
    t = _TRACK_PREFIX.sub("", stem)
    t = _JUNK.sub("", t)
    return re.sub(r"[_\s]+", " ", t).strip(" -_")


def _from_filename(path: Path) -> Track:
    stem = _clean_title(path.stem)
    for sep in (" - ", " – ", "-"):                                # частый вид имени: "Исполнитель - Трек"
        if sep in stem:
            artist, title = stem.split(sep, 1)
            if artist.strip() and title.strip():
                return Track(path, title.strip(), artist.strip())
    return Track(path, stem)


def _read_tags(path: Path) -> Optional[Track]:
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return None
    try:
        tags = MutagenFile(path, easy=True)
    except Exception:  # noqa: BLE001
        return None
    if not tags:
        return None
    title = (tags.get("title") or [""])[0].strip()
    artist = (tags.get("artist") or [""])[0].strip()
    if not title:
        return None
    return Track(path, title, artist)


def scan(force: bool = False) -> list[Track]:
    """Список треков в MUSIC_DIR. Результат кэшируется на несколько минут, чтобы не пересканировать
    папку на каждую команду — большая библиотека иначе заметно тормозила бы голосовой ответ."""
    folder = music_dir()
    key = str(folder)
    cached = _cache.get(key)
    if cached and not force and time.time() - cached[0] < RESCAN_SECONDS:
        return cached[1]

    tracks: list[Track] = []
    if folder.is_dir():
        try:
            for root, _dirs, files in os.walk(folder):
                for name in files:
                    if Path(name).suffix.lower() not in AUDIO_EXT:
                        continue
                    path = Path(root) / name
                    tracks.append(_read_tags(path) or _from_filename(path))
                    if len(tracks) >= MAX_FILES:
                        break
                if len(tracks) >= MAX_FILES:
                    break
        except OSError as e:
            log.warning("Не удалось прочитать папку с музыкой %s: %s", folder, e)
    _cache[key] = (time.time(), tracks)
    return tracks


def _score(query: str, track: Track) -> float:
    q = query.lower().strip()
    hay = track.search_text
    if q == track.title.lower() or q == track.artist.lower():
        return 3.0
    if q in hay:
        return 2.0 + len(q) / max(len(hay), 1)               # длиннее совпадение — точнее попадание
    words = [w for w in re.findall(r"\w+", q) if len(w) > 1]
    if not words:
        return 0.0
    hit = sum(1 for w in words if w in hay)
    return hit / len(words) if hit == len(words) else hit / len(words) * 0.6


def find(query: str, limit: int = 8) -> list[Track]:
    """Локальные треки, отсортированные по похожести на запрос. Пустой запрос -> вся библиотека."""
    tracks = scan()
    if not query.strip():
        return tracks[:limit]
    scored = [(t, _score(query, t)) for t in tracks]
    scored = [(t, s) for t, s in scored if s > 0]
    scored.sort(key=lambda p: p[1], reverse=True)
    return [t for t, _ in scored[:limit]]


# --------------------------------------------------------------------- запуск
def _open_file(path: Path) -> bool:
    try:
        if config.IS_WINDOWS:
            os.startfile(str(path))                            # type: ignore[attr-defined]
        elif config.IS_MAC:
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except OSError as e:
        log.warning("Не удалось открыть %s: %s", path, e)
        return False


def play_track(track: Track) -> str:
    if not _open_file(track.path):
        return f"Нашла «{track.display}», но не смогла её открыть."
    return f"Включаю «{track.display}»."


# ----------------------------------------------------------------- YouTube
def _youtube_search(query: str):
    """(заголовок, ссылка) первого результата, либо None. Ничего не скачивает."""
    try:
        import yt_dlp
    except ImportError:
        return None
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True,
           "default_search": "ytsearch1"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
    except Exception as e:  # noqa: BLE001
        log.info("Поиск на YouTube не удался: %s", e)
        return None
    entries = info.get("entries") or ([info] if info.get("id") else [])
    if not entries:
        return None
    top = entries[0]
    url = top.get("url") or f"https://www.youtube.com/watch?v={top.get('id')}"
    return top.get("title", query), url


def play_youtube(query: str) -> str:
    if not (getattr(config, "MUSIC_YOUTUBE_FALLBACK", True)):
        return f"В твоей папке с музыкой нет «{query}», а поиск на YouTube выключен в настройках."
    found = _youtube_search(query)
    if found is None:
        try:
            import yt_dlp  # noqa: F401
        except ImportError:
            return (f"В твоей папке с музыкой нет «{query}». Поиск на YouTube не работает — "
                    "не установлен пакет yt-dlp.")
        return f"Не нашла на YouTube ничего похожего на «{query}»."
    title, url = found
    webbrowser.open(url)
    return f"У тебя такого нет — открываю на YouTube: «{title}»."


# -------------------------------------------------------------- высокоуровневая команда
def play(query: str) -> str:
    """«Включи <что-нибудь>»: сначала своя библиотека, если не нашлось — YouTube."""
    query = query.strip()
    if not query:
        return "Что включить? Назови песню или исполнителя."
    matches = find(query, limit=1)
    if matches:
        return play_track(matches[0])
    return play_youtube(query)


def list_library(query: str = "", limit: int = 15) -> str:
    tracks = find(query, limit=limit) if query.strip() else scan()[:limit]
    if not tracks:
        folder = music_dir()
        if not folder.is_dir():
            return f"Папка с музыкой не найдена: {folder}. Укажи свою в настройках (MUSIC_DIR)."
        return "В папке с музыкой ничего не нашла." if query else "Папка с музыкой пуста."
    return "\n".join(f"- {t.display}" for t in tracks)
