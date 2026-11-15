#!/usr/bin/env python3
"""
Окно-персонаж поверх рабочего стола: Акира без рамки, с прозрачным фоном,
поверх всех окон.
Если есть assets/avatar.vrm и доступен QtWebEngine — запускает полноценного
3D VRM-персонажа.
Иначе — плавный откат к 2D спрайту (character.py).
"""
from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import config

try:
    from PySide6.QtCore import Qt, QTimer, QPoint, QUrl, QEvent
    from PySide6.QtGui import QImage, QPixmap, QGuiApplication, QAction
    from PySide6.QtWidgets import (
        QApplication, QLabel, QMenu, QSystemTrayIcon, QWidget, QVBoxLayout
    )
except ImportError:
    print("[avatar] PySide6 не установлен — окно персонажа пропущено.")
    sys.exit(0)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

import avatar_state
from character import CharacterRenderer


def _server_is_running(port: int = 8765) -> bool:
    s = socket.socket()
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        return False


def _ensure_avatar_server(port: int = 8765):
    if _server_is_running(port):
        return
    try:
        from akira.config import load_config
        from akira.avatar_server import AvatarServer
        cfg = load_config()
        cfg["avatar"]["open_browser"] = False
        srv = AvatarServer(cfg, config.BASE_DIR)
        srv.start()
    except Exception as e:
        print(f"[avatar] Не удалось запустить локальный сервер аватара: {e}")


class TransparentPage(QWebEnginePage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundColor(Qt.GlobalColor.transparent)


class Avatar3DWindow(QWidget):
    """3D VRM персонаж в отдельном прозрачном окне поверх рабочего стола."""

    def __init__(self) -> None:
        super().__init__()
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                 Qt.WindowType.Tool)
        if config.AVATAR_CLICK_THROUGH:
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        _ensure_avatar_server(8765)

        w = getattr(config, "AVATAR_WIDTH", 360)
        h = int(w * 1.45)
        self.resize(w, h)
        self._place_window()

        self._drag_origin: QPoint | None = None
        self._last_state = "idle"
        self._last_level = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView(self)
        self.view.setPage(TransparentPage(self.view))
        self.view.setStyleSheet("background: transparent;")
        self.view.load(QUrl("http://127.0.0.1:8765/?transparent=1"))
        layout.addWidget(self.view)

        self.view.installEventFilter(self)
        if self.view.focusProxy():
            self.view.focusProxy().installEventFilter(self)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._sync_state)
        self.timer.start(100)

        self._build_tray()
        self.show()

    def _place_window(self) -> None:
        pos = avatar_state.load_position()
        if pos:
            self.move(*pos)
            return
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 24, screen.bottom() - self.height() - 24)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        menu = QMenu()
        act_hide = QAction("Скрыть / показать", self)
        act_hide.triggered.connect(self._toggle_visible)
        act_quit = QAction("Закрыть Акиру (окно)", self)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_hide)
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Акира (3D)")
        try:
            self.tray.show()
        except Exception:
            pass

    def _toggle_visible(self) -> None:
        self.setVisible(not self.isVisible())

    def _sync_state(self) -> None:
        state, level, mood = avatar_state.read_state()
        if state != self._last_state or abs(level - self._last_level) > 0.08:
            self._last_state, self._last_level = state, level
            js = f"if (typeof handle === 'function') {{ handle({{type: 'state', state: '{state}'}}); }}"
            if level > 0.05:
                wlen = max(3, int(level * 16))
                js += f" if (typeof handle === 'function') {{ handle({{type: 'word', len: {wlen}}}); }}"
            self.view.page().runJavaScript(js)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = ev.globalPosition().toPoint() - self.pos()
        elif ev.type() == QEvent.Type.MouseMove and self._drag_origin is not None:
            self.move(ev.globalPosition().toPoint() - self._drag_origin)
        elif ev.type() == QEvent.Type.MouseButtonRelease:
            if self._drag_origin is not None:
                self._drag_origin = None
                avatar_state.save_position(self.x(), self.y())
        elif ev.type() == QEvent.Type.MouseButtonDblClick:
            self._toggle_visible()
        return super().eventFilter(obj, ev)


class Avatar2DWindow(QLabel):
    """Классический 2D персонаж (запасной вариант)."""

    def __init__(self) -> None:
        super().__init__()
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                 Qt.WindowType.Tool)
        if config.AVATAR_CLICK_THROUGH:
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.renderer = CharacterRenderer(config.AVATAR_WIDTH, transparent=True)
        self.resize(self.renderer.out_w, self.renderer.out_h)
        self._place_window()

        self._drag_origin: QPoint | None = None
        self._t0 = time.perf_counter()
        self._last_state = "idle"
        self._last_level = 0.0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000 // 30)

        self._build_tray()
        self._tick()
        self.show()

    def _place_window(self) -> None:
        pos = avatar_state.load_position()
        if pos:
            self.move(*pos)
            return
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 24, screen.bottom() - self.height() - 24)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        menu = QMenu()
        act_hide = QAction("Скрыть / показать", self)
        act_hide.triggered.connect(self._toggle_visible)
        act_quit = QAction("Закрыть Акиру (окно)", self)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_hide)
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Акира (2D)")
        try:
            self.tray.show()
        except Exception:
            pass

    def _toggle_visible(self) -> None:
        self.setVisible(not self.isVisible())

    def _tick(self) -> None:
        state, level, mood = avatar_state.read_state()
        self._last_state, self._last_level = state, level
        t = time.perf_counter() - self._t0
        frame = self.renderer.render(t, state, level, mood)
        h, w = frame.shape[:2]
        img = QImage(frame.data, w, h, w * 4, QImage.Format.Format_RGBA8888_Premultiplied)
        self.setPixmap(QPixmap.fromImage(img.copy()))

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = ev.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_origin is not None:
            self.move(ev.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, ev) -> None:
        if self._drag_origin is not None:
            self._drag_origin = None
            avatar_state.save_position(self.x(), self.y())

    def mouseDoubleClickEvent(self, ev) -> None:
        self._toggle_visible()


def main() -> None:
    if not config.ENABLE_AVATAR:
        return
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    vrm_exists = (config.BASE_DIR / "assets" / "avatar.vrm").exists()
    if HAS_WEBENGINE and vrm_exists:
        win = Avatar3DWindow()
    else:
        win = Avatar2DWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
