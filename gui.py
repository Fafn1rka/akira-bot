#!/usr/bin/env python3
"""
Окно управления Акирой: чат, статус подключений, сценарии, настройки и журнал — одна программа
вместо консоли. Акира при этом работает как обычно (голос, Telegram, Discord, персонаж на столе);
окно — это ещё один способ с ней говорить и настраивать её, а не замена остального.

Запуск:  run_gui.bat  (или Akira.vbs — тот же запуск, но без чёрного окна консоли).
Создать ярлык на рабочем столе и в меню Пуск:  create_shortcut.bat  (один раз).

Закрытие окна крестиком сворачивает программу в трей (у иконки в правом нижнем углу) — Акира
продолжает работать: отвечает в Telegram/Discord, слушает микрофон. Полностью выйти — через
трей: правой кнопкой по иконке -> «Выход», либо пункт «Выход» в меню окна.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import re
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from PySide6.QtCore import (QEvent, QMimeData, QObject, Qt, QTimer, QSize, Signal)
    from PySide6.QtGui import (QAction, QCloseEvent, QDragEnterEvent, QDropEvent,
                               QFont, QIcon, QImage, QKeyEvent, QPixmap)
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                                   QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                                   QListWidget, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
                                   QPushButton, QScrollArea, QSizePolicy, QSystemTrayIcon,
                                   QTabWidget, QTextEdit, QVBoxLayout, QWidget)
except ImportError:
    print("Для окна нужен пакет PySide6.\n  Windows:  .venv\\Scripts\\pip install PySide6\n"
         "  Linux:    .venv/bin/pip install PySide6")
    sys.exit(1)

import config
import envfile
import gui_core as gc
import imagegen
import mic_level
import links
import music
import quickmenu
import scenes
import spotify
import theme
from main import Akira

log = logging.getLogger("akira.gui")
ENV_PATH = HERE / ".env"
ICON_PATH = HERE / "assets" / "akira_icon.png"

# ============================================================ общий стиль
DARK_BG      = "#18181b"
PANEL_BG     = "#27272a"
BORDER_COLOR = "#3f3f46"
TEXT_COLOR   = "#e4e4e7"
ACCENT       = "#19c37d"
ACCENT_DARK  = "#15a368"
USER_BUBBLE  = "#166534"
BOT_BUBBLE   = "#27272a"

GLOBAL_STYLE = f"""
QWidget {{
    background: {DARK_BG};
    color: {TEXT_COLOR};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    background: {DARK_BG};
}}
QTabBar::tab {{
    background: {PANEL_BG};
    color: #a1a1aa;
    padding: 8px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    color: {TEXT_COLOR};
    border-bottom: 2px solid {ACCENT};
    background: {DARK_BG};
}}
QTabBar::tab:hover:!selected {{ color: {TEXT_COLOR}; }}
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {PANEL_BG};
    color: {TEXT_COLOR};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT};
}}
QPushButton {{
    background: {PANEL_BG};
    color: {TEXT_COLOR};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: #3f3f46; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #52525b; }}
QPushButton[accent="true"] {{
    background: {ACCENT};
    color: #fff;
    border: none;
}}
QPushButton[accent="true"]:hover {{ background: {ACCENT_DARK}; }}
QListWidget {{
    background: {PANEL_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item {{ padding: 6px 10px; border-radius: 4px; }}
QListWidget::item:selected {{ background: #3f3f46; color: {TEXT_COLOR}; }}
QListWidget::item:hover {{ background: #333336; }}
QScrollBar:vertical {{
    background: {DARK_BG};
    width: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: #52525b;
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #71717a; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 6px; background: {DARK_BG}; border-radius: 3px; }}
QScrollBar::handle:horizontal {{ background: #52525b; border-radius: 3px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: #71717a; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QProgressBar {{
    background: {PANEL_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    background: {PANEL_BG};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url(none);
}}
QComboBox {{
    background: {PANEL_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    padding: 5px 10px;
    color: {TEXT_COLOR};
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: {PANEL_BG};
    border: 1px solid {BORDER_COLOR};
    selection-background-color: #3f3f46;
    color: {TEXT_COLOR};
    outline: none;
}}
QFormLayout QLabel {{ color: #a1a1aa; }}
QLabel[title="true"] {{
    font-size: 15px;
    font-weight: bold;
    color: {TEXT_COLOR};
}}
QLabel[hint="true"] {{ color: #71717a; font-size: 11px; }}
QFrame[card="true"] {{
    background: {PANEL_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
}}
QScrollArea {{ border: none; background: {DARK_BG}; }}
"""


# ============================================================ фон: сама Акира
class Bridge(QObject):
    """Переносит ответы из фонового потока (где крутится asyncio) в окно — трогать виджеты
    можно только из главного потока, а сигналы Qt умеют это делать безопасно."""
    chat_reply = Signal(str)
    chat_error = Signal(str)
    scene_result = Signal(str)
    music_reply = Signal(str)
    menu_status = Signal(str)
    image_reply = Signal(str)


class Backend:
    """Сама Акира крутится в фоновом потоке (свой asyncio-цикл), окно — в главном (Qt)."""

    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge
        self.akira = Akira()
        self._thread = threading.Thread(target=self._run, name="akira-backend", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            asyncio.run(self.akira.run(headless=True))
        except Exception as e:  # noqa: BLE001
            log.exception("Акира остановилась с ошибкой: %s", e)

    @property
    def ready(self) -> bool:
        return self.akira.loop is not None

    def send(self, text: str, files: list[str] | None = None) -> None:
        if not self.ready:
            self.bridge.chat_error.emit("Ещё загружаюсь, секунду...")
            return

        async def go() -> None:
            try:
                reply = await self.akira.ask(text, files=files)
                self.bridge.chat_reply.emit(reply)
            except Exception as e:  # noqa: BLE001
                self.bridge.chat_error.emit(f"Ошибка: {e}")

        asyncio.run_coroutine_threadsafe(go(), self.akira.loop)

    def run_scene(self, name: str) -> None:
        def go() -> None:
            try:
                self.bridge.scene_result.emit(scenes.run_scene(name))
            except Exception as e:  # noqa: BLE001
                self.bridge.scene_result.emit(f"Ошибка: {e}")
        threading.Thread(target=go, daemon=True).start()

    def play_music(self, query: str) -> None:
        """Тот же инструмент, что вызывает голос/чат («включи ...») — файлы -> Spotify -> YouTube,
        с той же записью в историю и ту же отправку ссылки в Telegram/Discord."""
        def go() -> None:
            import extra_tools
            tools = {t.__name__: t for t in extra_tools.make_extra_tools(self.akira.brain, config.OWNER_KEY)}
            try:
                result = tools["play_music"](query)
            except Exception as e:  # noqa: BLE001
                result = f"Ошибка: {e}"
            self.bridge.music_reply.emit(result)
        threading.Thread(target=go, daemon=True).start()

    def run_menu_item(self, item: dict) -> None:
        action, value = item.get("action"), item.get("value", "")
        if action == "music":
            self.play_music(value)
        elif action == "scene":
            self.run_scene(value)
        elif action == "url":
            if value.strip().lower().startswith(("http://", "https://")):
                webbrowser.open(value)
                self.bridge.menu_status.emit(f"Открыла ссылку: {value}")
            else:
                self.bridge.menu_status.emit(f"Это не похоже на ссылку: {value}")
        elif action == "chat":
            self.send(value)
        else:
            self.bridge.menu_status.emit(f"Неизвестное действие: {action}")

    def generate_image(self, prompt: str) -> None:
        """Тот же инструмент, что вызывает голос/чат («нарисуй ...») — доставка в Telegram/Discord
        (если настроены) происходит сама, тут только запускаем и ждём подпись для статуса."""
        def go() -> None:
            import extra_tools
            tools = {t.__name__: t for t in extra_tools.make_extra_tools(self.akira.brain, config.OWNER_KEY)}
            try:
                result = tools["generate_image"](prompt)
            except Exception as e:  # noqa: BLE001
                result = f"Ошибка: {e}"
            self.bridge.image_reply.emit(result)
        threading.Thread(target=go, daemon=True).start()

    def stop(self) -> None:
        self.akira.request_stop()


# ==================================================================== чат (ChatGPT-стиль)

def _parse_code_blocks(text: str) -> list[tuple[str, str, bool]]:
    """Разбивает текст на части: (содержимое, язык, is_code).
    Возвращает список сегментов в порядке появления."""
    pattern = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)
    segments: list[tuple[str, str, bool]] = []
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            segments.append((text[last:m.start()], "", False))
        lang = m.group(1) or "code"
        segments.append((m.group(2).rstrip("\n"), lang, True))
        last = m.end()
    if last < len(text):
        segments.append((text[last:], "", False))
    return segments


def _md_to_html(text: str) -> str:
    """Конвертирует базовый markdown (ссылки, жирный, курсив, inline-code) в HTML."""
    # Экранируем HTML-теги
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Ссылки Markdown: [текст](url)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2" style="color:#19c37d; text-decoration:underline; font-weight:bold;">\1</a>',
        text
    )
    # Обычные ссылки: https://... (если не внутри href="")
    text = re.sub(
        r'(?<!href=")(https?://[^\s<"]+)',
        r'<a href="\1" style="color:#19c37d; text-decoration:underline;">\1</a>',
        text
    )
    # **жирный**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # *курсив*
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # `inline code`
    text = re.sub(
        r"`([^`]+?)`",
        r'<code style="background:#2d2d2d;color:#f8f8f2;padding:1px 5px;border-radius:3px;font-family:monospace;">\1</code>',
        text
    )
    # переносы строк
    text = text.replace("\n", "<br>")
    return text


class CodeBlock(QWidget):
    """Блок кода в стиле ChatGPT: тёмный фон, метка языка, кнопка копирования."""

    def __init__(self, code: str, lang: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._code = code

        container = QVBoxLayout(self)
        container.setContentsMargins(0, 0, 0, 0)
        container.setSpacing(0)

        # ---- заголовок: язык + кнопка
        header = QWidget()
        header.setStyleSheet("background:#1e1e1e; border-radius:6px 6px 0 0;")
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(10, 4, 10, 4)
        lang_lbl = QLabel(lang.lower() or "code")
        lang_lbl.setStyleSheet("color:#888; font-size:11px; font-family:monospace;")
        copy_btn = QPushButton("📋 Копировать")
        copy_btn.setStyleSheet(
            "QPushButton{color:#aaa;background:transparent;border:none;font-size:11px;}"
            "QPushButton:hover{color:#fff;}"
        )
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self._copy)
        h_row.addWidget(lang_lbl)
        h_row.addStretch()
        h_row.addWidget(copy_btn)
        self._copy_btn = copy_btn

        # ---- само тело кода
        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText(code)
        body.setFont(QFont("Consolas", 10))
        body.setStyleSheet(
            "QPlainTextEdit{"
            "  background:#282c34; color:#abb2bf;"
            "  border:none; border-radius:0 0 6px 6px;"
            "  padding:10px;"
            "}"
        )
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # авто-высота по контенту (макс 400px)
        lines = code.count("\n") + 1
        line_h = body.fontMetrics().lineSpacing()
        body.setFixedHeight(min(lines * line_h + 24, 400))
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        container.addWidget(header)
        container.addWidget(body)

        # ---- обёртка с отступами и бордером
        self.setStyleSheet(
            "CodeBlock{border:1px solid #3a3a3a; border-radius:6px; margin:6px 0;}"
        )

        # ---- кнопка «Применить» если это Python-файл-патч
        self._apply_btn: QPushButton | None = None
        if lang.lower() in ("python", "py", "diff", "patch"):
            apply_btn = QPushButton("⚡ Применить к проекту...")
            apply_btn.setStyleSheet(
                "QPushButton{color:#4ec9b0;background:#1e1e1e;border:1px solid #3a3a3a;"
                "border-radius:4px;padding:3px 8px;font-size:11px;margin:4px 0 0 0;}"
                "QPushButton:hover{background:#2d2d2d;}"
            )
            apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            apply_btn.clicked.connect(self._apply_to_project)
            container.addWidget(apply_btn)
            self._apply_btn = apply_btn

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._code)
        self._copy_btn.setText("✅ Скопировано!")
        QTimer.singleShot(2000, lambda: self._copy_btn.setText("📋 Копировать"))

    def _apply_to_project(self) -> None:
        """Предлагает применить код к выбранному файлу проекта."""
        path_str, ok = QInputDialog.getText(
            self, "Применить код",
            "Путь к файлу проекта (относительный или абсолютный):",
            text=""
        )
        if not ok or not path_str.strip():
            return
        target = Path(path_str.strip())
        if not target.is_absolute():
            target = HERE / target
        choice = QMessageBox.question(
            self, "Применить код",
            f"Перезаписать файл:\n{target}\n\nЭто заменит всё содержимое файла!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self._code, encoding="utf-8")
            QMessageBox.information(self, "Готово", f"Файл сохранён:\n{target}")
        except OSError as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось записать файл:\n{e}")


class MessageBubble(QFrame):
    """Один пузырёк сообщения: текст + (опционально) блоки кода."""

    _USER_STYLE = (
        "QFrame{background:#2f6b3e;border-radius:12px;padding:4px;}"
    )
    _BOT_STYLE = (
        "QFrame{background:#2d2d2d;border-radius:12px;padding:4px;}"
    )

    def __init__(self, who: str, text: str, is_user: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(self._USER_STYLE if is_user else self._BOT_STYLE)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setMaximumWidth(780)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Имя отправителя
        name_lbl = QLabel(f"<b style='color:{'#a5d6a7' if is_user else '#80cbc4'};'>{who}</b>")
        name_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(name_lbl)

        # Разбираем сегменты текста + блоки кода
        segments = _parse_code_blocks(text)
        for content, lang, is_code in segments:
            if is_code:
                block = CodeBlock(content, lang)
                layout.addWidget(block)
            else:
                stripped = content.strip()
                if not stripped:
                    continue
                lbl = QLabel(_md_to_html(stripped))
                lbl.setTextFormat(Qt.TextFormat.RichText)
                lbl.setWordWrap(True)
                lbl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse |
                    Qt.TextInteractionFlag.LinksAccessibleByMouse
                )
                lbl.setOpenExternalLinks(True)
                lbl.setStyleSheet("color:#e0e0e0; line-height:1.5;")
                layout.addWidget(lbl)


class ChatTab(QWidget):
    """Чат в стиле ChatGPT: пузырьки, выделение кода, drag-and-drop файлов, вставка из буфера."""

    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        self.backend = backend
        self._pending_files: list[str] = []  # файлы, прикреплённые к следующему сообщению

        # ---- прокручиваемая область сообщений
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._msg_container = QWidget()
        self._msg_container.setStyleSheet(f"background:{DARK_BG};")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._msg_layout.setContentsMargins(16, 16, 16, 16)
        self._msg_layout.setSpacing(12)
        self._msg_layout.addStretch(1)
        self._scroll.setWidget(self._msg_container)

        # ---- панель прикреплённых файлов
        self._attach_bar = QWidget()
        self._attach_bar.setStyleSheet(f"background:{PANEL_BG}; border-top:1px solid {BORDER_COLOR};")
        self._attach_bar.setVisible(False)
        attach_row = QHBoxLayout(self._attach_bar)
        attach_row.setContentsMargins(8, 4, 8, 4)
        self._attach_label = QLabel("")
        self._attach_label.setStyleSheet("color:#a1a1aa; font-size:11px;")
        clear_attach = QPushButton("✕")
        clear_attach.setMaximumWidth(28)
        clear_attach.setStyleSheet("QPushButton{background:transparent;border:none;color:#71717a;}"
                                   "QPushButton:hover{color:#e4e4e7;}")
        clear_attach.clicked.connect(self._clear_attachments)
        attach_row.addWidget(QLabel("📎"))
        attach_row.addWidget(self._attach_label, 1)
        attach_row.addWidget(clear_attach)

        # ---- поле ввода (многострочное) + drag-and-drop
        self.entry = _ChatInput(self)
        self.entry.setPlaceholderText(
            "Напиши Акире... (Enter — отправить, Shift+Enter — новая строка, "
            "Ctrl+V — вставить изображение или ссылку)")
        self.entry.setMaximumHeight(120)
        self.entry.files_dropped.connect(self._on_files_dropped)
        self.entry.installEventFilter(self)

        # кнопки
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)

        attach_btn = QPushButton("📎")
        attach_btn.setFixedSize(QSize(36, 36))
        attach_btn.setToolTip("Прикрепить файлы (изображения, документы, код...)")
        attach_btn.setStyleSheet(
            f"QPushButton{{background:{PANEL_BG};border:1px solid {BORDER_COLOR};"
            f"border-radius:8px;font-size:16px;color:#a1a1aa;}}"
            f"QPushButton:hover{{color:#e4e4e7;border-color:{ACCENT};}}"
        )
        attach_btn.clicked.connect(self._attach_files)

        send_btn = QPushButton("➤")
        send_btn.setFixedSize(QSize(40, 40))
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#fff;border-radius:8px;"
            f"font-size:18px;border:none;}}"
            f"QPushButton:hover{{background:{ACCENT_DARK};}}"
        )
        send_btn.clicked.connect(self._send)
        btn_row.addWidget(attach_btn)
        btn_row.addWidget(self.entry, 1)
        btn_row.addWidget(send_btn)

        # строка статуса «печатает...»
        self._typing_lbl = QLabel("")
        self._typing_lbl.setStyleSheet("color:#71717a; font-size:11px; margin-left:8px;")

        input_area = QWidget()
        input_area.setStyleSheet(f"background:{PANEL_BG}; border-top:1px solid {BORDER_COLOR};")
        input_outer = QVBoxLayout(input_area)
        input_outer.setContentsMargins(10, 6, 10, 10)
        input_outer.setSpacing(4)
        input_outer.addWidget(self._typing_lbl)
        input_outer.addLayout(btn_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._scroll)
        layout.addWidget(self._attach_bar)
        layout.addWidget(input_area)

        bridge.chat_reply.connect(self._on_reply)
        bridge.chat_error.connect(self._on_error)

        # Приветственное сообщение
        self._add_bubble(
            "Акира",
            "Привет! 👋 Напиши что-нибудь — отвечу текстом. "
            "Можешь прикрепить файл (📎), перетащить его мышью или вставить изображение/ссылку через Ctrl+V. "
            "Если пришлю код — нажми **📋 Копировать** или **⚡ Применить к проекту**.",
            is_user=False
        )

    # ------------------------------------------------------------------ drag-and-drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if files:
            self._on_files_dropped(files)

    # ------------------------------------------------------------------ attachments
    def _attach_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Прикрепить файлы", "",
            "Все файлы (*.*);;"
            "Изображения (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;"
            "Документы (*.pdf *.docx *.txt *.md *.py *.js *.ts *.json *.csv)"
        )
        if paths:
            self._on_files_dropped(paths)

    def _on_files_dropped(self, files: list[str]) -> None:
        self._pending_files.extend(files)
        names = ", ".join(Path(f).name for f in self._pending_files)
        self._attach_label.setText(names)
        self._attach_bar.setVisible(True)

    def _clear_attachments(self) -> None:
        self._pending_files.clear()
        self._attach_bar.setVisible(False)

    # ------------------------------------------------------------------ clipboard paste (Ctrl+V)
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.entry and event.type() == QEvent.Type.KeyPress:
            key_ev: QKeyEvent = event
            if key_ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if key_ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False  # Shift+Enter — перенос строки
                self._send()
                return True
            if key_ev.key() == Qt.Key.Key_V and key_ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
                cb = QApplication.clipboard()
                # 1. Картинка в буфере (скриншот)
                if cb.image() and not cb.image().isNull():
                    import tempfile
                    tmp = Path(tempfile.mktemp(suffix=".png"))
                    cb.image().save(str(tmp))
                    self._on_files_dropped([str(tmp)])
                    return True
                # 2. Файлы, скопированные в Проводнике (Ctrl+C по файлам)
                mime = cb.mimeData()
                if mime and mime.hasUrls():
                    local_files = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
                    if local_files:
                        self._on_files_dropped(local_files)
                        return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ send
    def _send(self) -> None:
        text = self.entry.toPlainText().strip()
        files = list(self._pending_files)
        if not text and not files:
            return
        # Формируем отображаемый текст для пузырька
        display = text
        if files:
            names = "\n".join(f"📎 {Path(f).name}" for f in files)
            display = f"{text}\n{names}" if text else names
        self._add_bubble("Ты", display, is_user=True)
        self.entry.clear()
        self._clear_attachments()
        self._typing_lbl.setText("Акира думает...")
        self.backend.send(text or "Посмотри на эти файлы.", files=files if files else None)

    # ------------------------------------------------------------------ receive
    def _on_reply(self, text: str) -> None:
        self._typing_lbl.setText("")
        self._add_bubble("Акира", text, is_user=False)

    def _on_error(self, text: str) -> None:
        self._typing_lbl.setText("")
        self._add_bubble("⚠ Ошибка", text, is_user=False)

    # ------------------------------------------------------------------ bubble
    def _add_bubble(self, who: str, text: str, *, is_user: bool) -> None:
        bubble = MessageBubble(who, text, is_user)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if is_user:
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)

        insert_pos = self._msg_layout.count() - 1
        self._msg_layout.insertLayout(insert_pos, row)
        QTimer.singleShot(50, self._scroll_bottom)

    def _scroll_bottom(self) -> None:
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())


class _ChatInput(QPlainTextEdit):
    """Поле ввода с поддержкой перетаскивания (drag-and-drop) файлов и веб-ссылок."""
    files_dropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls():
            local_files = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            web_urls = [u.toString() for u in mime.urls() if not u.isLocalFile()]
            if local_files:
                self.files_dropped.emit(local_files)
            if web_urls:
                self.insertPlainText(" " + " ".join(web_urls) + " ")
            event.acceptProposedAction()
        elif mime.hasText():
            self.insertPlainText(mime.text())
            event.acceptProposedAction()
        else:
            super().dropEvent(event)



# ==================================================================== статус
class _StatusCard(QFrame):
    """Одна карточка статуса: иконка + заголовок + значение."""
    def __init__(self, label: str) -> None:
        super().__init__()
        self.setProperty("card", True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self._dot = QLabel("●")
        self._dot.setFixedWidth(16)
        self._lbl = QLabel(label)
        self._lbl.setStyleSheet("color:#a1a1aa; min-width:130px;")
        self._val = QLabel("…")
        self._val.setWordWrap(True)
        layout.addWidget(self._dot)
        layout.addWidget(self._lbl)
        layout.addWidget(self._val, 1)

    def set_value(self, value: str, ok: Optional[bool]) -> None:
        color = {True: ACCENT, False: "#ef4444", None: "#71717a"}.get(ok, "#71717a")
        self._dot.setStyleSheet(f"color:{color}; font-size:10px;")
        self._val.setText(value)


class StatusTab(QWidget):
    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self.backend = backend
        self._cards: dict[str, _StatusCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)

        title = QLabel("Состояние системы")
        title.setProperty("title", True)
        outer.addWidget(title)

        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(6)
        outer.addLayout(self._cards_layout)

        # Микрофон
        mic_section = QLabel("Микрофон")
        mic_section.setStyleSheet("color:#71717a; font-size:11px; margin-top:10px;")
        outer.addWidget(mic_section)
        self.mic_bar = QProgressBar()
        self.mic_bar.setRange(0, 100)
        self.mic_bar.setTextVisible(False)
        self.mic_bar.setMaximumHeight(6)
        self.mic_label = QLabel("")
        self.mic_label.setProperty("hint", True)
        outer.addWidget(self.mic_bar)
        outer.addWidget(self.mic_label)
        outer.addStretch(1)

        self.timer = QTimer(self, interval=3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

        self.mic_timer = QTimer(self, interval=200)
        self.mic_timer.timeout.connect(self.refresh_mic)
        self.mic_timer.start()
        self.refresh_mic()

    def refresh(self) -> None:
        akira = self.backend.akira
        try:
            import discord_bot
            discord_running = discord_bot._instance is not None
        except Exception:  # noqa: BLE001
            discord_running = False
        rows = gc.build_status(
            ai_summary=akira.brain.describe(), ai_connected=akira.brain.available(),
            mic_enabled=config.VOICE_INPUT_ENABLED, mic_listening=config.VOICE_INPUT_ENABLED and self.backend.ready,
            telegram_configured=bool(config.TELEGRAM_BOT_TOKEN), telegram_running=akira.telegram_app is not None,
            discord_configured=bool(config.DISCORD_BOT_TOKEN), discord_running=discord_running,
            avatar_running=akira.avatar_proc is not None and akira.avatar_proc.poll() is None,
            reminders_pending=len(akira.brain.pending_reminders()),
        )
        for row in rows:
            if row.label not in self._cards:
                card = _StatusCard(row.label)
                self._cards[row.label] = card
                self._cards_layout.addWidget(card)
            self._cards[row.label].set_value(row.value, row.ok)

    def refresh_mic(self) -> None:
        if not config.VOICE_INPUT_ENABLED:
            self.mic_bar.setValue(0)
            self.mic_label.setText("Микрофон выключен в настройках.")
            return
        level, threshold, fresh = mic_level.read()
        if not fresh:
            self.mic_bar.setValue(0)
            self.mic_label.setText("Нет данных — микрофон ещё не слушает.")
            return
        scale = max(threshold * 2.0, 300.0)
        percent = int(max(0, min(100, level / scale * 100)))
        self.mic_bar.setValue(percent)
        speaking = level > threshold
        self.mic_label.setText("🎙 слышу речь" if speaking else "тихо / фоновый шум")



# ==================================================================== сценарии
class ScenesTab(QWidget):
    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        self.backend = backend

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ---- левая панель — список
        left_w = QFrame()
        left_w.setProperty("card", True)
        left_w.setFrameShape(QFrame.Shape.NoFrame)
        left_w.setMaximumWidth(230)
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(10, 10, 10, 10)
        lbl = QLabel("Сценарии")
        lbl.setProperty("title", True)
        left_l.addWidget(lbl)
        self.list = QListWidget()
        left_l.addWidget(self.list)
        new_btn = QPushButton("+ Создать")
        new_btn.setProperty("accent", True)
        left_l.addWidget(new_btn)
        layout.addWidget(left_w)

        # ---- правая панель — редактор
        right_w = QWidget()
        right_l = QVBoxLayout(right_w)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(8)
        right_l.addWidget(QLabel("Содержимое (JSON):"))
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setPlaceholderText(
            '{\n  "aliases": ["ещё-название"],\n  "say": "Что сказать",\n'
            '  "steps": [{"open": "vscode"}, {"volume": 25}]\n}')
        right_l.addWidget(self.editor)
        hint = QLabel("Шаги: open — программа/сайт, url — ссылка, volume (0–100), "
                      "media (play_pause/next/previous), wait — пауза.")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        right_l.addWidget(hint)
        btn_row = QHBoxLayout()
        save_btn = QPushButton("💾 Сохранить")
        run_btn = QPushButton("▶ Включить сейчас")
        run_btn.setProperty("accent", True)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(run_btn)
        right_l.addLayout(btn_row)
        layout.addWidget(right_w, 1)

        self.list.currentTextChanged.connect(self._select)
        save_btn.clicked.connect(self._save)
        run_btn.clicked.connect(self._run)
        new_btn.clicked.connect(self._new)
        bridge.scene_result.connect(lambda t: QMessageBox.information(self, "Сценарий", t))

        self._data: dict = {}
        self.reload()

    def reload(self) -> None:
        self._data = scenes.load_scenes()
        self.list.clear()
        self.list.addItems(list(self._data))

    def _select(self, name: str) -> None:
        import json
        if name in self._data:
            self.editor.setPlainText(json.dumps(self._data[name], ensure_ascii=False, indent=2))

    def _save(self) -> None:
        import json
        name = self.list.currentItem().text() if self.list.currentItem() else None
        if not name:
            QMessageBox.warning(self, "Сценарий", "Сначала выбери или создай сценарий слева.")
            return
        try:
            self._data[name] = json.loads(self.editor.toPlainText())
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "Сценарий", f"Ошибка JSON: {e}")
            return
        scenes.save_scenes(self._data)
        QMessageBox.information(self, "Сценарий", f"«{name}» сохранён.")

    def _run(self) -> None:
        item = self.list.currentItem()
        if item:
            self.backend.run_scene(item.text())

    def _new(self) -> None:
        name, okp = QInputDialog.getText(self, "Новый сценарий", "Название:")
        name = name.strip()
        if not okp or not name or name in self._data:
            return
        self._data[name] = {"steps": []}
        scenes.save_scenes(self._data)
        self.reload()
        self.list.setCurrentRow(list(self._data).index(name))


# ==================================================================== музыка
class MusicTab(QWidget):
    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        self.backend = backend

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # поиск
        search_row = QHBoxLayout()
        self.search = QLineEdit(placeholderText="🎵 Песня или исполнитель...")
        play_btn = QPushButton("▶ Включить")
        play_btn.setProperty("accent", True)
        fav_btn = QPushButton("★")
        fav_btn.setToolTip("В избранное")
        fav_btn.setMaximumWidth(36)
        add_file_btn = QPushButton("📁 Файлы...")
        search_row.addWidget(self.search)
        search_row.addWidget(play_btn)
        search_row.addWidget(fav_btn)
        search_row.addWidget(add_file_btn)
        layout.addLayout(search_row)

        self.status = QLabel("")
        self.status.setProperty("hint", True)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        # списки
        lists_row = QHBoxLayout()
        lists_row.setSpacing(12)
        # история
        hist_frame = QFrame()
        hist_frame.setProperty("card", True)
        hist_frame.setFrameShape(QFrame.Shape.NoFrame)
        hist_l = QVBoxLayout(hist_frame)
        hist_l.setContentsMargins(10, 10, 10, 10)
        hist_l.addWidget(QLabel("Недавно слушала:"))
        self.history_list = QListWidget()
        hist_l.addWidget(self.history_list)
        replay_h = QPushButton("▶ Включить снова")
        hist_l.addWidget(replay_h)
        lists_row.addWidget(hist_frame)
        # избранное
        fav_frame = QFrame()
        fav_frame.setProperty("card", True)
        fav_frame.setFrameShape(QFrame.Shape.NoFrame)
        fav_l = QVBoxLayout(fav_frame)
        fav_l.setContentsMargins(10, 10, 10, 10)
        fav_l.addWidget(QLabel("Избранное:"))
        self.fav_list = QListWidget()
        fav_l.addWidget(self.fav_list)
        remove_fav = QPushButton("✕ Убрать")
        fav_l.addWidget(remove_fav)
        lists_row.addWidget(fav_frame)
        layout.addLayout(lists_row)

        self.search.returnPressed.connect(self._play)
        play_btn.clicked.connect(self._play)
        fav_btn.clicked.connect(self._favorite)
        add_file_btn.clicked.connect(self._add_files)
        replay_h.clicked.connect(lambda: self._replay(self.history_list))
        remove_fav.clicked.connect(self._remove_favorite)
        bridge.music_reply.connect(self._on_reply)

        self._history_items: list[dict] = []
        self._fav_items: list[dict] = []
        self.timer = QTimer(self, interval=2000)
        self.timer.timeout.connect(self.reload)
        self.timer.start()
        self.reload()

    def reload(self) -> None:
        self._history_items = music.history(30)
        self.history_list.clear()
        self.history_list.addItems([h["label"] for h in self._history_items])
        self._fav_items = music.list_favorites()
        self.fav_list.clear()
        self.fav_list.addItems([f["label"] for f in self._fav_items])

    def _play(self) -> None:
        q = self.search.text().strip()
        if not q:
            return
        self.status.setText("Ищу...")
        self.backend.play_music(q)

    def _replay(self, widget: QListWidget) -> None:
        item = widget.currentItem()
        if item is None:
            return
        label = item.text()
        found = next((h for h in self._history_items + self._fav_items if h["label"] == label), None)
        if found and found.get("url") and music.open_location(found["url"]):
            self.status.setText(f"Включаю снова: {label}")
        else:
            self.status.setText("Ищу...")
            self.backend.play_music(label)

    def _favorite(self) -> None:
        q = self.search.text().strip()
        if not q:
            return
        music.add_favorite(q)
        self.reload()
        self.status.setText(f"«{q}» — в избранном.")

    def _add_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "Добавить музыку", "", "Аудио (*.mp3 *.flac *.wav *.ogg *.m4a *.opus *.aac *.wma)")
        if not paths:
            return
        for raw in paths:
            path = Path(raw)
            label = music._from_filename(path).display  # noqa: SLF001
            music.add_favorite(label, str(path))
        self.reload()
        self.status.setText(f"Добавила {len(paths)} файл(ов) в избранное." if len(paths) > 1
                            else "Добавила в избранное.")

    def _remove_favorite(self) -> None:
        item = self.fav_list.currentItem()
        if item is None:
            return
        music.remove_favorite(item.text())
        self.reload()

    def _on_reply(self, text: str) -> None:
        self.status.setText(text)
        self.reload()


# ==================================================================== ссылки
class LinksTab(QWidget):
    KINDS = ("Все", "музыка", "инфо")

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(QLabel("Фильтр:"))
        self.filter_box = QComboBox()
        self.filter_box.addItems(self.KINDS)
        top.addWidget(self.filter_box)
        top.addStretch(1)
        add_btn = QPushButton("+ Добавить ссылку")
        top.addWidget(add_btn)
        layout.addLayout(top)

        self.list = QListWidget()
        layout.addWidget(self.list)

        btn_row = QHBoxLayout()
        open_btn = QPushButton("🌐 Открыть")
        open_btn.setProperty("accent", True)
        copy_btn = QPushButton("📋 Скопировать")
        clear_btn = QPushButton("🗑 Очистить всё")
        btn_row.addWidget(open_btn)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        self.filter_box.currentTextChanged.connect(lambda _: self.reload())
        open_btn.clicked.connect(self._open)
        copy_btn.clicked.connect(self._copy)
        clear_btn.clicked.connect(self._clear)
        add_btn.clicked.connect(self._add)

        self._items: list[dict] = []
        self.timer = QTimer(self, interval=2000)
        self.timer.timeout.connect(self.reload)
        self.timer.start()
        self.reload()

    def reload(self) -> None:
        kind = self.filter_box.currentText()
        self._items = links.list_links(kind=None if kind == "Все" else kind, limit=100)
        self.list.clear()
        self.list.addItems([f"[{i['kind']}]  {i['title']}" for i in self._items])

    def _selected(self) -> Optional[dict]:
        row = self.list.currentRow()
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def _open(self) -> None:
        item = self._selected()
        if item:
            webbrowser.open(item["url"])

    def _copy(self) -> None:
        item = self._selected()
        if item:
            QApplication.clipboard().setText(item["url"])

    def _clear(self) -> None:
        if QMessageBox.question(self, "Ссылки", "Удалить все сохранённые ссылки?") == QMessageBox.StandardButton.Yes:
            links.clear()
            self.reload()

    def _add(self) -> None:
        url, okp = QInputDialog.getText(self, "Добавить ссылку", "Адрес (https://...):")
        url = url.strip()
        if not okp or not url:
            return
        if not url.lower().startswith(("http://", "https://")):
            QMessageBox.warning(self, "Ссылки", "Это не ссылка — начни с http:// или https://")
            return
        title, _ = QInputDialog.getText(self, "Добавить ссылку", "Название (необязательно):")
        links.add_link(url, title.strip() or url, "инфо", source="вручную")
        self.reload()


# ==================================================================== меню
class MenuTab(QWidget):
    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        self.backend = backend

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # левая панель — кнопки
        left_w = QFrame()
        left_w.setProperty("card", True)
        left_w.setFrameShape(QFrame.Shape.NoFrame)
        left_w.setMaximumWidth(230)
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(10, 10, 10, 10)
        lbl = QLabel("Быстрые кнопки")
        lbl.setProperty("title", True)
        left_l.addWidget(lbl)
        self.list = QListWidget()
        left_l.addWidget(self.list)
        run_btn = QPushButton("▶ Выполнить")
        run_btn.setProperty("accent", True)
        left_l.addWidget(run_btn)
        layout.addWidget(left_w)

        # правая панель — редактор
        right_w = QWidget()
        right_l = QVBoxLayout(right_w)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(8)

        form = QFormLayout()
        self.label_edit = QLineEdit(placeholderText="Название кнопки")
        self.action_box = QComboBox()
        self.action_box.addItems(list(quickmenu.ACTIONS))
        self.value_edit = QLineEdit(placeholderText="песня / ссылка / имя сценария / фраза")
        form.addRow("Название:", self.label_edit)
        form.addRow("Действие:", self.action_box)
        form.addRow("Значение:", self.value_edit)
        right_l.addLayout(form)

        hint = QLabel("music — трек, url — сайт, scene — сценарий, chat — фраза Акире.")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        right_l.addWidget(hint)

        btn_row = QHBoxLayout()
        new_btn = QPushButton("+ Новый")
        save_btn = QPushButton("💾 Сохранить")
        del_btn = QPushButton("🗑 Удалить")
        btn_row.addWidget(new_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(del_btn)
        right_l.addLayout(btn_row)
        right_l.addStretch(1)
        layout.addWidget(right_w, 1)

        self.list.currentRowChanged.connect(self._select)
        run_btn.clicked.connect(self._run)
        save_btn.clicked.connect(self._save)
        new_btn.clicked.connect(self._new)
        del_btn.clicked.connect(self._delete)
        bridge.menu_status.connect(lambda t: QMessageBox.information(self, "Меню", t))

        self._items: list[dict] = []
        self.reload()

    def reload(self) -> None:
        self._items = quickmenu.list_items()
        self.list.clear()
        self.list.addItems([i["label"] for i in self._items])

    def _select(self, row: int) -> None:
        if 0 <= row < len(self._items):
            item = self._items[row]
            self.label_edit.setText(item["label"])
            idx = list(quickmenu.ACTIONS).index(item["action"]) if item["action"] in quickmenu.ACTIONS else 0
            self.action_box.setCurrentIndex(idx)
            self.value_edit.setText(item["value"])

    def _current_row(self) -> int:
        return self.list.currentRow()

    def _run(self) -> None:
        row = self._current_row()
        if 0 <= row < len(self._items):
            self.backend.run_menu_item(self._items[row])

    def _save(self) -> None:
        label, value = self.label_edit.text().strip(), self.value_edit.text().strip()
        action = self.action_box.currentText()
        if not label or not value:
            QMessageBox.warning(self, "Меню", "Заполни название и значение.")
            return
        row = self._current_row()
        if 0 <= row < len(self._items):
            quickmenu.update_item(row, label, action, value)
        else:
            quickmenu.add_item(label, action, value)
        self.reload()

    def _new(self) -> None:
        self.list.clearSelection()
        self.label_edit.clear()
        self.value_edit.clear()
        self.action_box.setCurrentIndex(0)

    def _delete(self) -> None:
        row = self._current_row()
        if 0 <= row < len(self._items):
            quickmenu.remove_item(row)
            self.reload()
            self._new()


# ==================================================================== оформление
class AppearanceTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Оформление")
        title.setProperty("title", True)
        layout.addWidget(title)

        card = QFrame()
        card.setProperty("card", True)
        card.setFrameShape(QFrame.Shape.NoFrame)
        card_l = QFormLayout(card)
        card_l.setContentsMargins(16, 16, 16, 16)
        card_l.setSpacing(12)

        current = theme.load()
        self.preset_box = QComboBox()
        self.preset_box.addItems(list(theme.PRESETS))
        self.preset_box.setCurrentText(current["preset"])
        self.size_box = QComboBox()
        self.size_box.addItems([str(s) for s in theme.FONT_SIZES])
        self.size_box.setCurrentText(str(current["font_size"]))
        card_l.addRow("Тема:", self.preset_box)
        card_l.addRow("Размер шрифта:", self.size_box)
        layout.addWidget(card)

        apply_btn = QPushButton("✓ Применить тему")
        apply_btn.setProperty("accent", True)
        apply_btn.setMaximumWidth(200)
        layout.addWidget(apply_btn)

        note = QLabel("Изменения применяются мгновенно, перезапуск не нужен. "
                      "Эти настройки влияют только на вид окна.")
        note.setProperty("hint", True)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        apply_btn.clicked.connect(self._apply)

    def _apply(self) -> None:
        preset = self.preset_box.currentText()
        try:
            size = int(self.size_box.currentText())
        except ValueError:
            size = theme.DEFAULT_FONT_SIZE
        theme.save(preset, size)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet(preset, size))


# ==================================================================== картинки
class ImagesTab(QWidget):
    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        self.backend = backend

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.prompt = QLineEdit(placeholderText="🎨 Что нарисовать...")
        gen_btn = QPushButton("✨ Нарисовать")
        gen_btn.setProperty("accent", True)
        top.addWidget(self.prompt)
        top.addWidget(gen_btn)
        layout.addLayout(top)

        self.status = QLabel("")
        self.status.setProperty("hint", True)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        body = QHBoxLayout()
        body.setSpacing(12)

        left_frame = QFrame()
        left_frame.setProperty("card", True)
        left_frame.setFrameShape(QFrame.Shape.NoFrame)
        left_frame.setMaximumWidth(220)
        left_l = QVBoxLayout(left_frame)
        left_l.setContentsMargins(10, 10, 10, 10)
        self.list = QListWidget()
        left_l.addWidget(self.list)
        add_btn = QPushButton("📁 Добавить...")
        left_l.addWidget(add_btn)
        btn_row = QHBoxLayout()
        open_btn = QPushButton("🖼 Открыть")
        del_btn = QPushButton("🗑")
        del_btn.setMaximumWidth(36)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(del_btn)
        left_l.addLayout(btn_row)
        body.addWidget(left_frame)

        self.preview = QLabel("Выбери картинку →")
        self.preview.setMinimumSize(340, 340)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(f"background:{PANEL_BG}; border-radius:8px; color:#71717a;")
        body.addWidget(self.preview, 1)
        layout.addLayout(body)

        self.prompt.returnPressed.connect(self._generate)
        gen_btn.clicked.connect(self._generate)
        self.list.currentTextChanged.connect(self._show)
        open_btn.clicked.connect(self._open)
        del_btn.clicked.connect(self._delete)
        add_btn.clicked.connect(self._add_images)
        bridge.image_reply.connect(self._on_reply)

        self._paths: list[Path] = []
        self.timer = QTimer(self, interval=3000)
        self.timer.timeout.connect(self.reload)
        self.timer.start()
        self.reload()

    def reload(self) -> None:
        self._paths = imagegen.list_images()
        self.list.clear()
        self.list.addItems([p.name for p in self._paths])

    def _current_path(self) -> Optional[Path]:
        row = self.list.currentRow()
        return self._paths[row] if 0 <= row < len(self._paths) else None

    def _generate(self) -> None:
        q = self.prompt.text().strip()
        if not q:
            return
        self.status.setText("Рисую, это может занять минуту...")
        self.backend.generate_image(q)

    def _show(self, _name: str) -> None:
        path = self._current_path()
        if path is None:
            return
        pix = QPixmap(str(path))
        self.preview.setPixmap(pix.scaled(340, 340, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))

    def _open(self) -> None:
        path = self._current_path()
        if path:
            music._open_file(path)

    def _delete(self) -> None:
        path = self._current_path()
        if path and QMessageBox.question(self, "Картинки", f"Удалить «{path.name}»?") \
                == QMessageBox.StandardButton.Yes:
            try:
                path.unlink()
            except OSError:
                pass
            self.reload()

    def _add_images(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "Добавить картинки", "", "Картинки (*.png *.jpg *.jpeg *.gif *.webp *.bmp)")
        if not paths:
            return
        added = sum(1 for p in paths if imagegen.import_file(Path(p)) is not None)
        self.reload()
        self.status.setText(f"Добавила {added} картинк(и/у) в библиотеку." if added
                            else "Не удалось добавить ни одной картинки.")

    def _on_reply(self, text: str) -> None:
        self.status.setText(text)
        self.reload()


# ==================================================================== медиатека
class LibraryTab(QWidget):
    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        inner = QTabWidget()
        inner.addTab(MusicTab(backend, bridge), "🎵 Музыка")
        inner.addTab(ImagesTab(backend, bridge), "🖼 Картинки")
        inner.addTab(LinksTab(), "🔗 Ссылки")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner)


# ==================================================================== настройки
class SettingsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.widgets: dict[str, QWidget] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Настройки")
        title.setProperty("title", True)
        outer.addWidget(title)

        scroll = QScrollArea(widgetResizable=True)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        form_layout = QVBoxLayout(inner)
        form_layout.setContentsMargins(0, 8, 0, 8)
        form_layout.setSpacing(16)

        current = envfile.read(config.BASE_DIR / ".env")
        for group, fields in gc.SETTINGS_SCHEMA:
            card = QFrame()
            card.setProperty("card", True)
            card.setFrameShape(QFrame.Shape.NoFrame)
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(16, 12, 16, 12)
            card_l.setSpacing(8)
            grp_lbl = QLabel(group)
            grp_lbl.setStyleSheet("font-weight:bold; color:#a1a1aa; font-size:11px; letter-spacing:0.5px;")
            card_l.addWidget(grp_lbl)
            field_form = QFormLayout()
            field_form.setSpacing(8)
            for f in fields:
                value = current.get(f.key, f.default)
                if f.kind == "bool":
                    w = QCheckBox()
                    w.setChecked(gc.to_bool(value))
                else:
                    w = QLineEdit(value)
                    if f.kind == "secret":
                        w.setEchoMode(QLineEdit.EchoMode.Password)
                        toggle = QPushButton("👁", maximumWidth=32, checkable=True)
                        toggle.setStyleSheet("QPushButton{background:transparent;border:none;font-size:14px;}"
                                             "QPushButton:checked{color:#19c37d;}")
                        toggle.toggled.connect(lambda on, _w=w: _w.setEchoMode(
                            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
                        row_w = QWidget()
                        rl = QHBoxLayout(row_w)
                        rl.setContentsMargins(0, 0, 0, 0)
                        rl.addWidget(w)
                        rl.addWidget(toggle)
                        field_form.addRow(f.label + ":", row_w)
                        self.widgets[f.key] = w
                        if f.hint:
                            h = QLabel(f.hint)
                            h.setProperty("hint", True)
                            h.setWordWrap(True)
                            field_form.addRow("", h)
                        continue
                field_form.addRow(f.label + ":", w)
                self.widgets[f.key] = w
                if f.hint:
                    h = QLabel(f.hint)
                    h.setProperty("hint", True)
                    h.setWordWrap(True)
                    field_form.addRow("", h)
            card_l.addLayout(field_form)
            form_layout.addWidget(card)

        save = QPushButton("💾 Сохранить настройки")
        save.setProperty("accent", True)
        save.setMaximumWidth(220)
        note = QLabel("После сохранения перезапусти Акиру (Выход в трее → открой снова).")
        note.setProperty("hint", True)
        note.setWordWrap(True)
        form_layout.addWidget(save)
        form_layout.addWidget(note)
        form_layout.addStretch(1)
        save.clicked.connect(self._save)

    def _save(self) -> None:
        values: dict[str, str] = {}
        for key, w in self.widgets.items():
            values[key] = gc.from_bool(w.isChecked()) if isinstance(w, QCheckBox) else w.text().strip()
        try:
            envfile.apply(config.BASE_DIR / ".env", values)
        except OSError as e:
            QMessageBox.warning(self, "Настройки", f"Не удалось сохранить: {e}")
            return
        QMessageBox.information(self, "Настройки", "Сохранено. Перезапусти Акиру, чтобы применить.")



# ==================================================================== журнал
class LogTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel("Журнал работы (logs/akira.log)")
        title.setProperty("title", True)
        top.addWidget(title)
        top.addStretch(1)

        self.autoscroll_cb = QCheckBox("Автопрокрутка")
        self.autoscroll_cb.setChecked(True)
        top.addWidget(self.autoscroll_cb)

        copy_btn = QPushButton("📋 Скопировать")
        copy_btn.clicked.connect(self._copy_log)
        clear_btn = QPushButton("🗑 Очистить экран")
        clear_btn.clicked.connect(self._clear_view)
        top.addWidget(copy_btn)
        top.addWidget(clear_btn)
        layout.addLayout(top)

        self.view = QPlainTextEdit(readOnly=True)
        self.view.setMaximumBlockCount(3000)
        self.view.setFont(QFont("Consolas", 10))
        self.view.setStyleSheet(
            f"QPlainTextEdit {{ background:{DARK_BG}; color:#d4d4d8; "
            f"border:1px solid {BORDER_COLOR}; border-radius:6px; padding:10px; font-family:Consolas, monospace; }}"
        )
        layout.addWidget(self.view)

        self._size = 0
        self._path = config.LOGS_DIR / "akira.log"
        self.timer = QTimer(self, interval=1500)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _copy_log(self) -> None:
        QApplication.clipboard().setText(self.view.toPlainText())

    def _clear_view(self) -> None:
        self.view.clear()

    def _poll(self) -> None:
        try:
            size = self._path.stat().st_size
        except OSError:
            return
        if size == self._size:
            return
        try:
            text = self._path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        self._size = size
        self.view.setPlainText("\n".join(text.splitlines()[-600:]))
        if self.autoscroll_cb.isChecked():
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())


# ==================================================================== окно
class MainWindow(QWidget):
    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        self.backend = backend
        self.setWindowTitle("Акира — Голосовой компаньон")
        self.resize(920, 700)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        tabs = QTabWidget()
        tabs.addTab(ChatTab(backend, bridge), "💬 Чат")
        tabs.addTab(LibraryTab(backend, bridge), "📁 Медиатека")
        tabs.addTab(MenuTab(backend, bridge), "⚡ Меню")
        tabs.addTab(ScenesTab(backend, bridge), "🎬 Сценарии")
        tabs.addTab(StatusTab(backend), "📊 Статус")
        tabs.addTab(SettingsTab(), "⚙ Настройки")
        tabs.addTab(AppearanceTab(), "🎨 Оформление")
        tabs.addTab(LogTab(), "📜 Журнал")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(tabs)

        self.tray = QSystemTrayIcon(QIcon(str(ICON_PATH)) if ICON_PATH.exists() else QIcon())
        menu = QMenu()
        open_action = QAction("Открыть окно", self)
        quit_action = QAction("Выход (закрыть совсем)", self)
        open_action.triggered.connect(self._show)
        quit_action.triggered.connect(self._quit)
        menu.addAction(open_action)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Акира")
        self.tray.activated.connect(
            lambda reason: self._show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        self._closing = False

    def _show(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._closing = True
        try:
            (config.DATA_DIR / "gui.lock").unlink(missing_ok=True)
        except Exception:
            pass
        self.backend.stop()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            event.accept()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage("Акира", "Свернула в трей — продолжаю работать.\n"
                              "Чтобы выйти совсем: правой кнопкой по значку возле часов -> «Выход».",
                              QSystemTrayIcon.MessageIcon.Information, 4000)


def check_single_instance() -> bool:
    """Проверяет, не запущена ли уже другая копия Акиры."""
    lock_path = config.DATA_DIR / "gui.lock"
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            old_pid = int(lock_path.read_text(encoding="utf-8").strip())
            if old_pid != os.getpid():
                # Проверяем, жив ли процесс
                if config.IS_WINDOWS:
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    SYNCHRONIZE = 0x00100000
                    handle = kernel32.OpenProcess(SYNCHRONIZE, False, old_pid)
                    if handle:
                        kernel32.CloseHandle(handle)
                        return False
                else:
                    try:
                        os.kill(old_pid, 0)
                        return False
                    except OSError:
                        pass
        except Exception:
            pass
    try:
        lock_path.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    return True


def main() -> None:
    if "--avatar" in sys.argv:
        import avatar
        avatar.main()
        return

    config.LOGS_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(config.LOGS_DIR / "akira.log", encoding="utf-8")])

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(GLOBAL_STYLE)

    if not check_single_instance():
        QMessageBox.warning(
            None,
            "Акира уже запущена",
            "Акира уже работает на компьютере (возможно, свёрнута в трей возле часов).\n\n"
            "Не запускайте несколько копий программы одновременно — иначе они конфликтуют "
            "(включая Telegram-бота).\n\n"
            "Проверьте значок Акиры в правом нижнем углу экрана (возле часов)."
        )
        sys.exit(0)

    bridge = Bridge()
    backend = Backend(bridge)
    backend.start()

    window = MainWindow(backend, bridge)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
