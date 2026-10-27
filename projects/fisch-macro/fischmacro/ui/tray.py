"""System tray icon with quick controls and notifications."""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from fischmacro import APP_NAME
from fischmacro.automation.engine import Status


class Tray:
    def __init__(self, window, icon):
        self.window = window
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self.icon = QSystemTrayIcon(icon, window) if self.available else None
        if not self.icon:
            return
        menu = QMenu()
        self.a_show = QAction("Show window", menu, triggered=self._show)
        self.a_start = QAction("Start", menu, triggered=window.start_automation)
        self.a_pause = QAction("Pause / resume", menu, triggered=window.ctx.engine.toggle_pause)
        self.a_stop = QAction("Emergency stop", menu, triggered=window.emergency_stop)
        self.a_quit = QAction("Quit", menu, triggered=window.close)
        for a in (self.a_show, None, self.a_start, self.a_pause, self.a_stop, None, self.a_quit):
            menu.addSeparator() if a is None else menu.addAction(a)
        self.menu = menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(lambda reason: reason == QSystemTrayIcon.Trigger and self._show())

    def _show(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def set_visible(self, on: bool) -> None:
        if self.icon:
            self.icon.setVisible(on)

    def update(self, status: Status, catches: int) -> None:
        if not self.icon:
            return
        self.icon.setToolTip(f"{APP_NAME} - {status.value} - {catches} catches")
        running = status in (Status.RUNNING, Status.PAUSED)
        self.a_start.setEnabled(not running)
        self.a_pause.setEnabled(running)

    def notify(self, title: str, message: str, error: bool = False) -> None:
        if self.icon and self.icon.isVisible():
            self.icon.showMessage(title, message,
                                  QSystemTrayIcon.Critical if error else QSystemTrayIcon.Information, 5000)
