' Запускает окно Акиры без чёрного окна консоли. Двойной клик — как обычная программа.
' Ярлыки на рабочий стол и в меню Пуск, указывающие на этот файл, создаёт create_shortcut.bat.
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = folder
python = folder & "\.venv\Scripts\python.exe"
If Not fso.FileExists(python) Then
    WshShell.Popup "Сначала запусти install.bat — он ещё не выполнялся.", 0, "Акира", 48
    WScript.Quit 1
End If
' 0 = окно скрыто; python.exe (не pythonw.exe) — тогда консоль есть, но невидима, и обычные
' print()/логи не падают с ошибкой "stream is None", как бывает у pythonw.exe.
WshShell.Run """" & python & """ gui.py", 0, False
