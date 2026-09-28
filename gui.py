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
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QCloseEvent, QIcon, QPixmap
    from PySide6.QtWidgets import (QApplication, QCheckBox, QFormLayout, QFrame, QHBoxLayout,
                                   QLabel, QLineEdit, QListWidget, QMenu, QMessageBox, QPlainTextEdit,
                                   QPushButton, QScrollArea, QSystemTrayIcon, QTabWidget, QTextEdit,
                                   QVBoxLayout, QWidget)
except ImportError:
    print("Для окна нужен пакет PySide6.\n  Windows:  .venv\\Scripts\\pip install PySide6\n"
         "  Linux:    .venv/bin/pip install PySide6")
    sys.exit(1)

import config
import envfile
import gui_core as gc
import scenes
from main import Akira

log = logging.getLogger("akira.gui")
ENV_PATH = HERE / ".env"
ICON_PATH = HERE / "assets" / "akira_character.png"


# ============================================================ фон: сама Акира
class Bridge(QObject):
    """Переносит ответы из фонового потока (где крутится asyncio) в окно — трогать виджеты
    можно только из главного потока, а сигналы Qt умеют это делать безопасно."""
    chat_reply = Signal(str)
    chat_error = Signal(str)
    scene_result = Signal(str)


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
        tabs.addTab(StatusTab(backend), "Статус")
        tabs.addTab(ScenesTab(backend, bridge), "Сценарии")
        tabs.addTab(SettingsTab(), "Настройки")
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
    config.LOGS_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(config.LOGS_DIR / "akira.log", encoding="utf-8")])

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    bridge = Bridge()
    backend = Backend(bridge)
    backend.start()

    window = MainWindow(backend, bridge)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
