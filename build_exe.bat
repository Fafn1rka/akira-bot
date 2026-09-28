@echo off
REM Собирает Акиру в ОДИН файл AkiraGUI.exe (папка dist\), который запускается без Python
REM и без чёрного окна — почти как готовая программа. Собирать нужно на СВОЁМ Windows,
REM .exe для этого компьютера не переносится на другой с другой версией Windows/Python.
REM Занимает несколько минут и требует интернета (первый раз).
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Сначала запусти install.bat
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
pip install -r requirements-build.txt
if errorlevel 1 (
    echo Не удалось установить PyInstaller — проверь интернет.
    pause
    exit /b 1
)

echo.
echo Собираю AkiraGUI.exe (несколько минут)...
pyinstaller --noconfirm akira.spec
if errorlevel 1 (
    echo Сборка не удалась — смотри текст ошибки выше.
    pause
    exit /b 1
)

echo.
echo Готово: dist\AkiraGUI.exe
echo ВАЖНО: рядом с .exe нужны папка .env (твои ключи) и data\ (память Акиры) —
echo        .exe их не содержит, они должны лежать в той же папке, что и .exe.
echo Дальше можно собрать настоящий установщик: installer.iss (нужен Inno Setup, см. README).
pause
