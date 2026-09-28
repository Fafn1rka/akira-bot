#!/usr/bin/env python3
"""Разовая авторизация Акиры в твоём Spotify. Запускай через spotify_login.bat.
Откроется браузер — войди в свой аккаунт Spotify и разреши доступ. После этого Акира сможет
искать и включать треки прямо в Spotify («Акира, включи ...»)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import spotify as sp_mod


def main() -> None:
    if not sp_mod.configured():
        print("Сначала впиши в .env:")
        print("  SPOTIFY_CLIENT_ID=...")
        print("  SPOTIFY_CLIENT_SECRET=...")
        print("Получить: https://developer.spotify.com/dashboard -> Create app")
        print(f"Redirect URI в настройках приложения впиши ТОЧНО: {config.SPOTIFY_REDIRECT_URI}")
        return
    try:
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        print("Не установлен пакет spotipy: .venv\\Scripts\\pip install spotipy")
        return

    auth = SpotifyOAuth(
        client_id=config.SPOTIFY_CLIENT_ID, client_secret=config.SPOTIFY_CLIENT_SECRET,
        redirect_uri=config.SPOTIFY_REDIRECT_URI, scope=sp_mod.SCOPE,
        cache_path=str(sp_mod.CACHE_PATH), open_browser=True,
    )
    print("Открываю браузер для входа в Spotify...")
    print(f"Если браузер не откроется сам — перейди по ссылке и вернись сюда с адресом,"
         f" на который тебя перекинет (начинается на {config.SPOTIFY_REDIRECT_URI}).")
    try:
        token = auth.get_access_token(as_dict=False)
    except Exception as e:  # noqa: BLE001
        print(f"Не получилось авторизоваться: {e}")
        return
    if token:
        print("Готово! Теперь скажи Акире «включи ...», и она поищет трек в твоём Spotify.")
        print("Не забудь открыть приложение Spotify на устройстве, где должна играть музыка.")
    else:
        print("Не получилось авторизоваться — попробуй ещё раз.")


if __name__ == "__main__":
    main()
