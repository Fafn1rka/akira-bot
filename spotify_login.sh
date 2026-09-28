#!/usr/bin/env bash
# Разовая авторизация Акиры в Spotify (нужен Premium). См. README.md, раздел «Spotify».
cd "$(dirname "$0")"
source .venv/bin/activate
python spotify_login.py
