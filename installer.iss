; Установщик Акиры для Windows — Inno Setup (бесплатно: jrsoftware.org/isinfo.php).
; Собирает то, что получилось после build_exe.bat, в один AkiraSetup.exe: с иконками
; на рабочем столе и в меню Пуск, и с обычным удалением через «Параметры -> Приложения»,
; как у игр или офисных программ.
;
; Как использовать:
;   1) Сначала запусти build_exe.bat — должен появиться dist\AkiraGUI.exe
;   2) Поставь Inno Setup Compiler (один раз)
;   3) Открой этот файл (installer.iss) через Inno Setup Compiler -> Build -> Compile
;   4) Готовый установщик появится в Output\AkiraSetup.exe

#define MyAppName "Акира"
#define MyAppVersion "1.0"
#define MyAppExeName "AkiraGUI.exe"

[Setup]
AppId={{A6B4F1B0-9C1B-4B2E-8B8E-AKIRA00000001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Akira
DefaultGroupName=Акира
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=AkiraSetup
Compression=lzma
SolidCompression=yes
SetupIconFile=assets\akira.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example"; DestDir: "{app}"; DestName: ".env"; Flags: onlyifdoesntexist
; Забирает ВСЁ содержимое папки data, если оно уже есть рядом (память Акиры, сценарии)
Source: "data\*"; DestDir: "{app}\data"; Flags: recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\Акира"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Удалить Акиру"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Акира"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "notepad.exe"; Parameters: """{app}\.env"""; Description: "Открыть .env и вписать ключ AI"; Flags: postinstall skipifsilent nowait
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить Акиру сейчас"; Flags: postinstall skipifsilent nowait unchecked
