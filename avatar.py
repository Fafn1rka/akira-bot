#!/usr/bin/env python3
"""
Окно-персонаж поверх рабочего стола: Акира без рамки, с прозрачным фоном,
поверх всех окон. Реагирует на state/level из avatar_state.py (пишет их
основной процесс бота — см. voice.py и main.py).

Отдельный процесс: если PySide6 не установлен или окружение без графики
(сервер без монитора), просто ничего не делаем — на боте это не сказывается.
Запуск: main.py сам стартует `python avatar.py` при ENABLE_AVATAR=True.
Двойной клик — свернуть/развернуть. Перетаскивание — мышью, позиция
запоминается между запусками. Правая кнопка — контекстное меню (выход).
"""
from __future__ import annotations

import sys
import time

import config

try:
    from PySide6.QtCore import Qt, QTimer, QPoint
    from PySide6.QtGui import QImage, QPixmap, QGuiApplication, QAction
    from PySide6.QtWidgets import QApplication, QLabel, QMenu, QSystemTrayIcon
except ImportError:
    print("[avatar] PySide6 не установлен — окно персонажа пропущено. "
          "Поставь: pip install PySide6")
    sys.exit(0)

import avatar_state
from character import CharacterRenderer


class AvatarWindow(QLabel):
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
        self.timer.start(1000 // 30)  # 30 fps достаточно для плавности и лёгкое для CPU

        self._build_tray()
        self._tick()
        self.show()

    # ------------------------------------------------------------- вид
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
        self.tray.setToolTip("Акира")
        # без иконки трей может не показаться на некоторых DE — это не критично
        try:
            self.tray.show()
        except Exception:  # noqa: BLE001
            pass

    def _toggle_visible(self) -> None:
        self.setVisible(not self.isVisible())

    # ------------------------------------------------------------ кадр
    def _tick(self) -> None:
        state, level = avatar_state.read_state()
        self._last_state, self._last_level = state, level
        t = time.perf_counter() - self._t0
        frame = self.renderer.render(t, state, level)  # premultiplied RGBA, uint8 (H,W,4)
        h, w = frame.shape[:2]
        img = QImage(frame.data, w, h, w * 4, QImage.Format.Format_RGBA8888_Premultiplied)
        self.setPixmap(QPixmap.fromImage(img.copy()))

    # ------------------------------------------------------- перетаскивание
    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = ev.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag_origin is not None:
            self.move(ev.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if self._drag_origin is not None:
            self._drag_origin = None
            avatar_state.save_position(self.x(), self.y())

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        self._toggle_visible()


def main() -> None:
    if not config.ENABLE_AVATAR:
        return
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    win = AvatarWindow()  # noqa: F841 — держим ссылку живой
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
