@echo off
REM Создаёт ярлык «Акира» на рабочем столе и в меню Пуск — после этого программу можно
REM открывать как любую другую (иконка, двойной клик, поиск в меню Пуск), без чёрного окна.
REM Достаточно запустить один раз (после install.bat).
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Сначала запусти install.bat
    pause
    exit /b 1
)

set "ICON=%~dp0assets\akira_character.png"
if not exist "%ICON%" set "ICON=%~dp0.venv\Scripts\python.exe"

> "%TEMP%\akira_shortcut.vbs" (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo Set fso = CreateObject^("Scripting.FileSystemObject"^)
    echo target = "%~dp0Akira.vbs"
    echo icon = "%ICON%"
    echo For Each folder In Array^(WshShell.SpecialFolders^("Desktop"^), WshShell.SpecialFolders^("StartMenu"^) ^& "\Programs"^)
    echo     Set link = WshShell.CreateShortcut^(folder ^& "\Акира.lnk"^)
    echo     link.TargetPath = "wscript.exe"
    echo     link.Arguments = """" ^& target ^& """"
    echo     link.WorkingDirectory = "%~dp0"
    echo     If fso.GetExtensionName^(icon^) = "exe" Then
    echo         link.IconLocation = icon
    echo     End If
    echo     link.Description = "Акира — голосовой ИИ-компаньон"
    echo     link.Save
    echo Next
)
cscript //nologo "%TEMP%\akira_shortcut.vbs"
del "%TEMP%\akira_shortcut.vbs"

echo.
echo Готово: ярлык «Акира» появился на рабочем столе и в меню Пуск.
pause
