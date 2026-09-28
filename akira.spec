# -*- mode: python ; coding: utf-8 -*-
# Собирает окно Акиры в один AkiraGUI.exe. Используется через build_exe.bat — обычно этот файл
# руками не трогают. Пересобрать: .venv\Scripts\pyinstaller --noconfirm akira.spec
import sys
from pathlib import Path

block_cipher = None
HERE = Path.cwd()

# Всё нужное Акире, что PyInstaller сам не находит: картинки персонажа, скины document-разбора и т.д.
datas = [
    (str(HERE / "assets"), "assets"),
    (str(HERE / ".env.example"), "."),
]

a = Analysis(
    ["gui.py"],
    pathex=[str(HERE)],
    datas=datas,
    hiddenimports=[
        "config", "envfile", "gui_core", "scenes", "briefing", "screen", "mediakeys",
        "brain", "providers", "persona", "system_control", "memory", "media", "voice",
        "voice_listener", "stt", "extra_tools", "avatar_state", "character",
        "telegram_bot", "discord_bot", "twitch_bot",
    ],
    hookspath=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="AkiraGUI",
    console=False,                       # без чёрного окна консоли — как обычная программа
    icon=str(HERE / "assets" / "akira_character.png") if (HERE / "assets" / "akira_character.png").exists() else None,
    onefile=True,
)
