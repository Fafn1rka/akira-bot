@echo off
chcp 65001 >nul
REM Диагностика: почему Акира не слышит голос и не переключается на Ollama.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python check.py
echo.
pause
