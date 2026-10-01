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
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QCloseEvent, QIcon, QPixmap
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QFrame,
                                   QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                                   QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                                   QSystemTrayIcon, QTabWidget, QTextEdit, QVBoxLayout, QWidget)
except ImportError:
    print("Для окна нужен пакет PySide6.\n  Windows:  .venv\\Scripts\\pip install PySide6\n"
         "  Linux:    .venv/bin/pip install PySide6")
    sys.exit(1)

import config
import envfile
import gui_core as gc
import imagegen
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

    def send(self, text: str) -> None:
        if not self.ready:
            self.bridge.chat_error.emit("Ещё загружаюсь, секунду...")
            return

        async def go() -> None:
            try:
                reply = await self.akira.ask(text)
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


# ==================================================================== чат
class ChatTab(QWidget):
    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        self.backend = backend
        self.log = QTextEdit(readOnly=True)
        self.entry = QLineEdit(placeholderText="Напиши Акире и нажми Enter...")
        send = QPushButton("Отправить")

        layout = QVBoxLayout(self)
        layout.addWidget(self.log)
        row = QHBoxLayout()
        row.addWidget(self.entry)
        row.addWidget(send)
        layout.addLayout(row)

        self.entry.returnPressed.connect(self._send)
        send.clicked.connect(self._send)
        bridge.chat_reply.connect(self._on_reply)
        bridge.chat_error.connect(self._on_reply)

    def _send(self) -> None:
        text = self.entry.text().strip()
        if not text:
            return
        self._append("Ты", text)
        self.entry.clear()
        self.backend.send(text)

    def _on_reply(self, text: str) -> None:
        self._append("Акира", text)

    def _append(self, who: str, text: str) -> None:
        self.log.append(f"<b>{who}:</b> {text}")
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())


# ==================================================================== статус
class StatusTab(QWidget):
    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self.backend = backend
        self.rows: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        layout.addStretch(1)
        self.form = form

        self.timer = QTimer(self, interval=3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

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
            label = self.rows.get(row.label)
            if label is None:
                label = self.rows[row.label] = QLabel()
                self.form.addRow(row.label + ":", label)
            color = {"True": "#2e7d32", "False": "#c62828"}.get(str(row.ok), "#616161")
            label.setText(f'<span style="color:{color}">{row.value}</span>')


# ==================================================================== сценарии
class ScenesTab(QWidget):
    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        self.backend = backend
        self.list = QListWidget()
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText('{\n  "aliases": ["ещё-название"],\n  "say": "Что сказать",\n'
                                       '  "steps": [{"open": "vscode"}, {"volume": 25}]\n}')
        run_btn, save_btn, new_btn, hint = (QPushButton("Включить сейчас"), QPushButton("Сохранить"),
                                            QPushButton("Новый"), QLabel())
        hint.setWordWrap(True)
        hint.setText("Шаги сценария: open (программа/сайт), url (ссылка), volume (0–100), "
                    "media (play_pause/next/previous), wait (пауза, секунды).")

        left = QVBoxLayout()
        left.addWidget(QLabel("Сценарии:"))
        left.addWidget(self.list)
        left.addWidget(new_btn)

        right = QVBoxLayout()
        right.addWidget(QLabel("Содержимое выбранного сценария (в формате JSON):"))
        right.addWidget(self.editor)
        right.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(save_btn)
        row.addWidget(run_btn)
        right.addLayout(row)

        top = QHBoxLayout(self)
        left_w, right_w = QWidget(), QWidget()
        left_w.setLayout(left)
        right_w.setLayout(right)
        left_w.setMaximumWidth(220)
        top.addWidget(left_w)
        top.addWidget(right_w)

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
            QMessageBox.warning(self, "Сценарий", f"Это не похоже на правильный JSON: {e}")
            return
        scenes.save_scenes(self._data)
        QMessageBox.information(self, "Сценарий", f"«{name}» сохранён.")

    def _run(self) -> None:
        item = self.list.currentItem()
        if item:
            self.backend.run_scene(item.text())

    def _new(self) -> None:
        from PySide6.QtWidgets import QInputDialog
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
        self.search = QLineEdit(placeholderText="Песня или исполнитель...")
        play_btn = QPushButton("Включить")
        fav_btn = QPushButton("★ В избранное")
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.history_list = QListWidget()
        self.fav_list = QListWidget()
        replay_h = QPushButton("Включить снова")
        remove_fav = QPushButton("Убрать из избранного")

        top = QHBoxLayout()
        top.addWidget(self.search)
        top.addWidget(play_btn)
        top.addWidget(fav_btn)

        lists = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Недавно слушала:"))
        left.addWidget(self.history_list)
        left.addWidget(replay_h)
        right = QVBoxLayout()
        right.addWidget(QLabel("Избранное:"))
        right.addWidget(self.fav_list)
        right.addWidget(remove_fav)
        left_w, right_w = QWidget(), QWidget()
        left_w.setLayout(left)
        right_w.setLayout(right)
        lists.addWidget(left_w)
        lists.addWidget(right_w)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.status)
        layout.addLayout(lists)

        self.search.returnPressed.connect(self._play)
        play_btn.clicked.connect(self._play)
        fav_btn.clicked.connect(self._favorite)
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
        if found and found.get("url"):
            webbrowser.open(found["url"])
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
        self.filter_box = QComboBox()
        self.filter_box.addItems(self.KINDS)
        self.list = QListWidget()
        open_btn = QPushButton("Открыть")
        copy_btn = QPushButton("Скопировать ссылку")
        clear_btn = QPushButton("Очистить всё")

        top = QHBoxLayout()
        top.addWidget(QLabel("Показывать:"))
        top.addWidget(self.filter_box)
        top.addStretch(1)

        row = QHBoxLayout()
        row.addWidget(open_btn)
        row.addWidget(copy_btn)
        row.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.list)
        layout.addLayout(row)

        self.filter_box.currentTextChanged.connect(lambda _t: self.reload())
        open_btn.clicked.connect(self._open)
        copy_btn.clicked.connect(self._copy)
        clear_btn.clicked.connect(self._clear)

        self._items: list[dict] = []
        self.timer = QTimer(self, interval=2000)
        self.timer.timeout.connect(self.reload)
        self.timer.start()
        self.reload()

    def reload(self) -> None:
        kind = self.filter_box.currentText()
        self._items = links.list_links(kind=None if kind == "Все" else kind, limit=100)
        self.list.clear()
        self.list.addItems([f"[{i['kind']}] {i['title']}" for i in self._items])

    def _selected(self) -> Optional[dict]:
        row = self.list.currentRow() if hasattr(self.list, "currentRow") else -1
        if row is None or row < 0 or row >= len(self._items):
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


# ==================================================================== меню
class MenuTab(QWidget):
    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        self.backend = backend
        self.list = QListWidget()
        self.label_edit = QLineEdit(placeholderText="Название кнопки")
        self.action_box = QComboBox()
        self.action_box.addItems(list(quickmenu.ACTIONS))
        self.value_edit = QLineEdit(placeholderText="песня / ссылка / имя сценария / фраза")
        hint = QLabel("music — включить трек, url — открыть сайт, scene — сценарий, "
                     "chat — отправить Акире фразу.")
        hint.setWordWrap(True)

        run_btn, save_btn, new_btn, del_btn = (QPushButton("Выполнить"), QPushButton("Сохранить"),
                                               QPushButton("Новый пункт"), QPushButton("Удалить"))

        left = QVBoxLayout()
        left.addWidget(QLabel("Твои кнопки:"))
        left.addWidget(self.list)
        left.addWidget(run_btn)

        form = QFormLayout()
        form.addRow("Название:", self.label_edit)
        form.addRow("Действие:", self.action_box)
        form.addRow("Значение:", self.value_edit)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addWidget(hint)
        btn_row = QHBoxLayout()
        btn_row.addWidget(new_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(del_btn)
        right.addLayout(btn_row)
        right.addStretch(1)

        top = QHBoxLayout(self)
        left_w, right_w = QWidget(), QWidget()
        left_w.setLayout(left)
        right_w.setLayout(right)
        left_w.setMaximumWidth(220)
        top.addWidget(left_w)
        top.addWidget(right_w)

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
        return self.list.currentRow() if hasattr(self.list, "currentRow") else -1

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
        self.list.clearSelection() if hasattr(self.list, "clearSelection") else None
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
        current = theme.load()
        self.preset_box = QComboBox()
        self.preset_box.addItems(list(theme.PRESETS))
        self.preset_box.setCurrentText(current["preset"])
        self.size_box = QComboBox()
        self.size_box.addItems([str(s) for s in theme.FONT_SIZES])
        self.size_box.setCurrentText(str(current["font_size"]))
        apply_btn = QPushButton("Применить")
        note = QLabel("Меняется сразу — Акиру перезапускать не нужно. Это только про то, как "
                     "выглядит окно; на голос, Telegram и Discord не влияет.")
        note.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Тема:", self.preset_box)
        form.addRow("Размер шрифта:", self.size_box)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(apply_btn)
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
        self.prompt = QLineEdit(placeholderText="Что нарисовать...")
        gen_btn = QPushButton("Нарисовать")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.list = QListWidget()
        self.preview = QLabel("Выбери картинку слева")
        self.preview.setMinimumSize(320, 320)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        open_btn = QPushButton("Открыть")
        del_btn = QPushButton("Удалить")

        top = QHBoxLayout()
        top.addWidget(self.prompt)
        top.addWidget(gen_btn)

        left = QVBoxLayout()
        left.addWidget(self.list)
        row = QHBoxLayout()
        row.addWidget(open_btn)
        row.addWidget(del_btn)
        left.addLayout(row)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setMaximumWidth(240)

        body = QHBoxLayout()
        body.addWidget(left_w)
        body.addWidget(self.preview, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.status)
        layout.addLayout(body)

        self.prompt.returnPressed.connect(self._generate)
        gen_btn.clicked.connect(self._generate)
        self.list.currentTextChanged.connect(self._show)
        open_btn.clicked.connect(self._open)
        del_btn.clicked.connect(self._delete)
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
        row = self.list.currentRow() if hasattr(self.list, "currentRow") else -1
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
        self.preview.setPixmap(pix.scaled(320, 320, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))

    def _open(self) -> None:
        path = self._current_path()
        if path:
            music._open_file(path)  # тот же «открыть в программе по умолчанию», что и для музыки

    def _delete(self) -> None:
        path = self._current_path()
        if path and QMessageBox.question(self, "Картинки", f"Удалить «{path.name}»?") \
                == QMessageBox.StandardButton.Yes:
            try:
                path.unlink()
            except OSError:
                pass
            self.reload()

    def _on_reply(self, text: str) -> None:
        self.status.setText(text)
        self.reload()


# ==================================================================== настройки
class SettingsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.widgets: dict[str, QWidget] = {}
        outer = QVBoxLayout(self)
        scroll = QScrollArea(widgetResizable=True)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        form = QVBoxLayout(inner)

        current = envfile.read(config.BASE_DIR / ".env")
        for group, fields in gc.SETTINGS_SCHEMA:
            box = QFrame()
            box_l = QFormLayout(box)
            title = QLabel(f"<b>{group}</b>")
            form.addWidget(title)
            for f in fields:
                value = current.get(f.key, f.default)
                if f.kind == "bool":
                    w = QCheckBox()
                    w.setChecked(gc.to_bool(value))
                else:
                    w = QLineEdit(value)
                    if f.kind == "secret":
                        w.setEchoMode(QLineEdit.EchoMode.Password)
                        toggle = QPushButton("👁", maximumWidth=28, checkable=True)
                        toggle.toggled.connect(lambda on, w=w: w.setEchoMode(
                            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
                        row = QWidget()
                        rl = QHBoxLayout(row)
                        rl.setContentsMargins(0, 0, 0, 0)
                        rl.addWidget(w)
                        rl.addWidget(toggle)
                        box_l.addRow(f.label + ":", row)
                        self.widgets[f.key] = w
                        if f.hint:
                            box_l.addRow("", QLabel(f'<span style="color:#888">{f.hint}</span>'))
                        continue
                box_l.addRow(f.label + ":", w)
                self.widgets[f.key] = w
                if f.hint:
                    box_l.addRow("", QLabel(f'<span style="color:#888">{f.hint}</span>'))
            form.addWidget(box)

        save = QPushButton("Сохранить настройки")
        save.clicked.connect(self._save)
        note = QLabel("После сохранения перезапусти Акиру (Выход в трее, затем снова открой окно) —"
                     " настройки читаются при старте.")
        note.setWordWrap(True)
        form.addWidget(save)
        form.addWidget(note)
        form.addStretch(1)

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
        self.view = QPlainTextEdit(readOnly=True)
        self.view.setMaximumBlockCount(2000)
        layout = QVBoxLayout(self)
        layout.addWidget(self.view)
        self._size = 0
        self._path = config.LOGS_DIR / "akira.log"
        self.timer = QTimer(self, interval=1500)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

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
        was_bottom = self.view.verticalScrollBar().value() >= self.view.verticalScrollBar().maximum() - 4
        self.view.setPlainText("\n".join(text.splitlines()[-500:]))
        if was_bottom:
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())


# ==================================================================== окно
class MainWindow(QWidget):
    def __init__(self, backend: Backend, bridge: Bridge) -> None:
        super().__init__()
        self.backend = backend
        self.setWindowTitle("Акира")
        self.resize(760, 560)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        tabs = QTabWidget()
        tabs.addTab(ChatTab(backend, bridge), "Чат")
        tabs.addTab(MusicTab(backend, bridge), "Музыка")
        tabs.addTab(LinksTab(), "Ссылки")
        tabs.addTab(MenuTab(backend, bridge), "Меню")
        tabs.addTab(ImagesTab(backend, bridge), "Картинки")
        tabs.addTab(ScenesTab(backend, bridge), "Сценарии")
        tabs.addTab(StatusTab(backend), "Статус")
        tabs.addTab(SettingsTab(), "Настройки")
        tabs.addTab(AppearanceTab(), "Оформление")
        tabs.addTab(LogTab(), "Журнал")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        self.tray = QSystemTrayIcon(QIcon(str(ICON_PATH)) if ICON_PATH.exists() else QIcon())
        menu = QMenu()
        open_action = QAction("Открыть", self)
        quit_action = QAction("Выход", self)
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
        self.tray.showMessage("Акира", "Свернула в трей — продолжаю работать. "
                              "Чтобы выйти совсем: правой кнопкой по значку -> «Выход».",
                              QSystemTrayIcon.MessageIcon.Information, 4000)


def main() -> None:
    if "--avatar" in sys.argv:
        # Внутри AkiraGUI.exe своего отдельного avatar.py как файла нет — этот же .exe с флагом
        # --avatar запускает только окно персонажа (его отдельно вызывает main.py, см. _start_avatar).
        import avatar
        avatar.main()
        return

    config.LOGS_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(config.LOGS_DIR / "akira.log", encoding="utf-8")])

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    saved_theme = theme.load()
    app.setStyleSheet(theme.stylesheet(saved_theme["preset"], saved_theme["font_size"]))

    bridge = Bridge()
    backend = Backend(bridge)
    backend.start()

    window = MainWindow(backend, bridge)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
