@echo off
REM Установка Акиры на Windows. Просто дважды кликни этот файл.
chcp 65001 >nul
cd /d "%~dp0"

echo == Akira: install (Windows) ==

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.10+ from python.org
    echo IMPORTANT: on the install screen, check "Add python.exe to PATH".
    pause
    exit /b 1
)

python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

if not exist .env (
    copy .env.example .env >nul
    echo.
    echo ^>^>^> Created .env file - open it and fill in GEMINI_API_KEY ^(and TELEGRAM_BOT_TOKEN if needed^).
)

echo.
echo Done!
echo.
echo Two ways to run Akira:
echo   run.bat          - console window (text log, type to chat)
echo   create_shortcut.bat  - creates an "Akira" icon on Desktop / Start Menu (a real window,
echo                          chat/status/scenes/settings - no console). Run it once.
echo Check the microphone with test_mic.bat
echo Diagnose voice/Ollama problems with check.bat
pause
