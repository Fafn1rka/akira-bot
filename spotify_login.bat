@echo off
REM Разовая авторизация Акиры в твоём Spotify. Запусти ОДИН РАЗ после того, как впишешь
REM SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET в .env (как их получить — см. README.md).
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Сначала запусти install.bat
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python spotify_login.py
echo.
pause
