@echo off
REM Тот же запуск окна Акиры, но с видимой консолью — удобно, если что-то не открывается,
REM чтобы увидеть текст ошибки. Обычный способ запуска — Akira.vbs или ярлык с рабочего стола.
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Сначала запусти install.bat
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python gui.py
if errorlevel 1 pause
