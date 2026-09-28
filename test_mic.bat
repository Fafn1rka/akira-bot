@echo off
REM Проверка микрофона: показывает список устройств и что Акира слышит и распознаёт.
chcp 65001 >nul
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo === Микрофоны (номер можно вписать в .env как VOICE_MIC_DEVICE) ===
python voice_listener.py --devices
echo.
echo === Проверка распознавания. Говори — Ctrl+C для выхода ===
python voice_listener.py --test
pause
