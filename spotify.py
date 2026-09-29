"""
Включает конкретный трек прямо в твоём Spotify (не локальный файл и не YouTube) — искать можно
по всему каталогу Spotify, а не только по тому, что у тебя скачано.

Нужен Spotify PREMIUM: без него Spotify не разрешает запускать воспроизведение через API (искать
всё равно можно, но не включить). Пауза/следующий/предыдущий трек отдельного кода не требуют —
это уже умеет media_control через системные медиаклавиши, пока в Spotify что-то играет.

Настройка (один раз, минут пять):
    1. https://developer.spotify.com/dashboard -> Create app.
       Redirect URI впиши ТОЧНО (без пробелов и лишних /): http://127.0.0.1:8888/callback
    2. Client ID и Client Secret со страницы приложения -> в .env:
         SPOTIFY_CLIENT_ID=...
         SPOTIFY_CLIENT_SECRET=...
    3. Запусти spotify_login.bat — один раз, откроется браузер: войди в Spotify и разреши доступ.
    4. На устройстве, где должна играть музыка (телефон, компьютер), приложение Spotify должно
       быть ОТКРЫТО (хотя бы на паузе) — иначе Spotify не знает, куда включать трек.

Авторизация — только через spotify_login.bat, в обычном окне консоли. Внутри самой Акиры (окно,
фоновый поток, Telegram) она никогда сама не пытается открыть браузер для входа — это могло бы
надолго зависнуть там, где нет способа ответить на запрос браузера.
"""
from __future__ import annotations

import logging
from typing import Optional

import config

log = logging.getLogger("akira.spotify")

SCOPE = "user-modify-playback-state user-read-playback-state"
CACHE_PATH = config.DATA_DIR / "spotify_token.json"

_client_cache = None


def configured() -> bool:
    return bool(config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET)


def available() -> bool:
    """Можно пользоваться прямо сейчас: пакет есть, ключи вписаны и spotify_login.bat уже запускали."""
    try:
        import spotipy  # noqa: F401
    except ImportError:
        return False
    return configured() and CACHE_PATH.exists()


def status() -> str:
    """Почему недоступно (для сообщений пользователю)."""
    try:
        import spotipy  # noqa: F401
    except ImportError:
        return "Пакет spotipy не установлен: .venv\\Scripts\\pip install spotipy"
    if not configured():
        return "Spotify не настроен — впиши SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET в .env."
    if not CACHE_PATH.exists():
        return "Spotify ещё не авторизован — запусти spotify_login.bat один раз."
    return "готов"


def _client():
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    # open_browser=False: если кешированный токен вдруг не обновится сам — не пытаемся открыть
    # браузер из фонового потока (Акира может работать без консоли, там некому на это ответить).
    auth = SpotifyOAuth(
        client_id=config.SPOTIFY_CLIENT_ID, client_secret=config.SPOTIFY_CLIENT_SECRET,
        redirect_uri=config.SPOTIFY_REDIRECT_URI, scope=SCOPE,
        cache_path=str(CACHE_PATH), open_browser=False,
    )
    _client_cache = spotipy.Spotify(auth_manager=auth)
    return _client_cache


def _label(track: dict) -> str:
    artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
    name = track.get("name", "")
    return f"{artists} — {name}" if artists else name


def _active_device(sp) -> Optional[str]:
    try:
        devices = (sp.devices() or {}).get("devices", [])
    except Exception as e:  # noqa: BLE001
        log.info("Не удалось получить список устройств Spotify: %s", e)
        return None
    if not devices:
        return None
    active = next((d for d in devices if d.get("is_active")), None)
    return (active or devices[0])["id"]


def play(query: str, capture: Optional[dict] = None) -> str:
    """capture, если передан, заполняется {"url","title","kind"} — так вызывающий код (extra_tools.py)
    может сохранить ссылку на вкладку «Ссылки» и прислать её в Telegram/Discord."""
    if not available():
        return status()
    try:
        sp = _client()
        result = sp.search(q=query, type="track", limit=1)
        items = ((result or {}).get("tracks") or {}).get("items") or []
        if not items:
            return f"Не нашла в Spotify ничего похожего на «{query}»."
        track = items[0]
        device_id = _active_device(sp)
        if device_id is None:
            return (f"Нашла в Spotify «{_label(track)}», но не вижу открытого устройства — "
                    "открой приложение Spotify (на телефоне или компьютере) и попробуй снова.")
        sp.start_playback(device_id=device_id, uris=[track["uri"]])
        if capture is not None:
            url = (track.get("external_urls") or {}).get("spotify", "")
            capture.update(url=url, title=_label(track), kind="музыка")
        return f"Включаю в Spotify «{_label(track)}»."
    except Exception as e:  # noqa: BLE001
        log.warning("Spotify: ошибка воспроизведения: %s", e)
        msg = str(e).lower()
        if "premium" in msg or "403" in msg:
            return "Spotify отказал — включать треки через голос может только Spotify Premium."
        return f"Spotify не смог включить трек ({type(e).__name__})."
