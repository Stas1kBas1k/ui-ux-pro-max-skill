from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from fischmacro import APP_NAME, __version__
from fischmacro.automation.engine import Status
from fischmacro.diagnostics.snapshot import save_snapshot
from fischmacro.input.hotkeys import normalize_combo
from fischmacro.profiles.schema import HOTKEY_ACTIONS
from fischmacro.profiles.manager import ProfileError
from fischmacro.ui.calibration import CalibrationWindow
from fischmacro.ui.fancy import ToastManager, asset_pixmap
from fischmacro.ui.icons import icon
from fischmacro.ui.overlay import DebugOverlay
from fischmacro.ui.pages.automation import AutomationPage
from fischmacro.ui.pages.dashboard import DashboardPage
from fischmacro.ui.pages.hotkeys import HotkeysPage
from fischmacro.ui.pages.logs import LogsPage
from fischmacro.ui.pages.profiles import ProfilesPage
from fischmacro.ui.pages.settings import SettingsPage, open_folder
from fischmacro.ui.pages.vision import VisionPage
from fischmacro.ui.theme import C, STATE, STATUS_COLORS
from fischmacro.ui.tray import Tray
from fischmacro.ui.widgets import label
from fischmacro.vision.capture import CaptureError

log = logging.getLogger(__name__)

RISK_TEXT = (
    "<p><b>Before you start</b></p>"
    "<p>Fisch Macro automates fishing in Roblox Fisch by looking at your screen and sending normal mouse and "
    "keyboard input. It does not read game memory, inject code or bypass anti-cheat.</p>"
    "<p><b>Third-party automation can break Roblox's Terms of Use or the game's rules and may put your account "
    "at risk.</b> You are responsible for how you use it.</p>"
    "<ul><li>Everything runs locally. Screenshots are never uploaded and no account data is read.</li>"
    "<li>Automation never starts by itself. Use Start / F6, and F8 for an immediate emergency stop.</li>"
    "<li>Calibrate the screen regions for your setup first (Computer Vision &rarr; Calibrate).</li>"
    "<li>Try <i>Simulation</i> capture mode in Settings to see the whole loop without the game.</li></ul>"
)


def app_icon() -> QIcon:
    art = asset_pixmap("app_icon.png")
    return QIcon(art) if art is not None else icon("fish", C["primary_hi"], 64)


class RiskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - first run")
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        text = QLabel(RISK_TEXT)
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        v.addWidget(text)
        self.chk = QCheckBox("I understand the risks and want to continue")
        v.addWidget(self.chk)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setEnabled(False)
        self.ok.setObjectName("primary")
        self.chk.toggled.connect(self.ok.setEnabled)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class MainWindow(QMainWindow):
    NAV = [("dashboard", "Dashboard"), ("automation", "Automation"), ("vision", "Computer Vision"),
           ("profiles", "Profiles"), ("hotkeys", "Hotkeys"), ("settings", "Settings"), ("logs", "Logs & Statistics")]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1100, 720)
        self.resize(1320, 860)
        self.overlay = DebugOverlay()
        self.calibration: CalibrationWindow | None = None
        self._local_shortcuts: list[QShortcut] = []
        self._tick = 0
        self._stats_dirty = False
        self.rebuilding = False
        self._last_catches = 0

        root = QWidget()
        root.setObjectName("root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        self.stack.setObjectName("root")
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.dashboard = DashboardPage(ctx)
        self.automation = AutomationPage(ctx)
        self.vision = VisionPage(ctx)
        self.profiles = ProfilesPage(ctx)
        self.hotkeys = HotkeysPage(ctx)
        self.settings = SettingsPage(ctx)
        self.logs = LogsPage(ctx)
        for page in (self.dashboard, self.automation, self.vision, self.profiles, self.hotkeys, self.settings, self.logs):
            self.stack.addWidget(page)

        self.dashboard.start_requested.connect(self.start_automation)
        self.dashboard.pause_requested.connect(self.ctx.engine.toggle_pause)
        self.dashboard.stop_requested.connect(self.emergency_stop)
        self.vision.calibrate_requested.connect(self.toggle_calibration)
        self.vision.snapshot_requested.connect(self.diagnostic_snapshot)
        self.vision.overlay_toggled.connect(self.set_overlay)
        ctx.hotkey.connect(self.on_hotkey, Qt.QueuedConnection)
        ctx.profile_switched.connect(self.on_profile_switched)

        self._build_statusbar()
        self.toasts = ToastManager(self.stack)
        self.tray = Tray(self, app_icon())
        self.tray.set_visible(ctx.settings.notifications.tray_icon)
        ctx.settings_changed.connect(self._on_settings_changed)
        for i in range(len(self.NAV)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.select_page(i))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(66)
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.logs.refresh_stats)
        self.stats_timer.start(5000)
        self.select_page(0)
        self._restore_geometry()

    # ------------------------------------------------------------------ chrome
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(int(232 * max(1.0, STATE["base_pt"] / 10.5)))
        v = QVBoxLayout(side)
        v.setContentsMargins(14, 18, 14, 14)
        v.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        art = asset_pixmap("logo.png")
        if art is not None:
            dpr = self.devicePixelRatioF()
            pm = art.scaled(int(46 * dpr), int(46 * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            logo.setPixmap(pm)
        else:
            logo.setPixmap(icon("fish", C["primary_hi"], 30).pixmap(30, 30))
        brand.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(APP_NAME, "brand"))
        col.addWidget(label(f"v{__version__} · local vision", "brandSub"))
        brand.addLayout(col, 1)
        v.addLayout(brand)
        v.addSpacing(18)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for i, (key, text) in enumerate(self.NAV):
            b = QPushButton(icon(key, C["muted"]), "  " + text.replace("&", "&&"))
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setIconSize(QSize(18, 18))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.select_page(i))
            self.nav_group.addButton(b, i)
            v.addWidget(b)
        v.addStretch(1)
        v.addWidget(label("PROFILE", "tileLabel"))
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("Quick profile switch (locked while automation runs)")
        self._fill_profiles()
        self.profile_combo.activated.connect(self._quick_switch)
        v.addWidget(self.profile_combo)
        v.addSpacing(8)
        self.side_status = label("Stopped", "cardTitle")
        self.side_hint = label("F6 start · F7 pause · F8 stop", "faint")
        box = QFrame()
        box.setObjectName("tile")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(12, 10, 12, 10)
        bv.addWidget(label("STATUS", "tileLabel"))
        bv.addWidget(self.side_status)
        bv.addWidget(self.side_hint)
        v.addWidget(box)
        return side

    def _fill_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(self.ctx.profiles.names())
        self.profile_combo.setCurrentText(self.ctx.profile.name)
        self.profile_combo.blockSignals(False)

    def _quick_switch(self, _index: int) -> None:
        name = self.profile_combo.currentText()
        if name and name != self.ctx.profile.name:
            try:
                self.ctx.switch_profile(name)
                self.toast("Profile", f"Switched to '{name}'", C["primary_hi"])
            except ProfileError as exc:
                self._fill_profiles()
                QMessageBox.warning(self, "Profiles", str(exc))

    def _on_settings_changed(self) -> None:
        self.tray.set_visible(self.ctx.settings.notifications.tray_icon)

    def toast(self, title: str, message: str, color: str | None = None) -> None:
        if self.ctx.settings.notifications.toasts:
            self.toasts.show(title, message, color)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "toasts"):
            self.toasts.reposition()

    def changeEvent(self, e):
        super().changeEvent(e)
        if (e.type() == QEvent.WindowStateChange and self.isMinimized() and
                self.ctx.settings.notifications.minimize_to_tray and self.tray.icon and self.tray.icon.isVisible()):
            QTimer.singleShot(0, self.hide)

    def _notify_events(self, events) -> None:
        n = self.ctx.settings.notifications
        for _, kind, msg in events:
            if kind in ("error", "disconnect"):
                self.toast("Automation stopped" if kind == "error" else "Disconnected", msg, C["danger"])
                if n.desktop_notifications:
                    self.tray.notify("Fisch Macro", msg, error=True)
                if n.sound_on_error:
                    QApplication.beep()
            elif kind == "reminder":
                self.toast("Reminder", msg, C["primary_hi"])
                if n.desktop_notifications:
                    self.tray.notify("Fisch Macro reminder", msg)
            elif kind == "info" and ("limit" in msg.lower() or "finished" in msg.lower()):
                self.toast("Session", msg, C["accent"])
                if n.desktop_notifications:
                    self.tray.notify("Fisch Macro", msg)
            elif kind == "warning" and "EMERGENCY" in msg:
                self.toast("Emergency stop", "All inputs released.", C["warning"])
        catches = self.ctx.engine.session.catches
        every = n.notify_every_catches
        if every and catches != self._last_catches and catches % every == 0 and catches > 0:
            self.tray.notify("Fisch Macro", f"{catches} catches this session")
            self.toast("Milestone", f"{catches} catches this session", C["success"])
        self._last_catches = catches

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.sb_profile = QLabel()
        self.sb_capture = QLabel()
        self.sb_fps = QLabel()
        self.sb_keys = QLabel()
        for w in (self.sb_profile, self.sb_capture, self.sb_fps):
            sb.addWidget(w)
        sb.addPermanentWidget(self.sb_keys)

    def select_page(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        for j, (key, _) in enumerate(self.NAV):
            b = self.nav_group.button(j)
            b.setChecked(j == i)
            b.setIcon(icon(key, C["primary_hi"] if j == i else C["muted"]))
        self.ctx.engine.set_preview(self.stack.currentWidget() is self.vision)

    def _restore_geometry(self) -> None:
        g = self.ctx.settings.window_geometry
        if g and self.ctx.settings.startup.remember_geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(g.encode()))
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ hotkeys
    def install_local_shortcuts(self) -> None:
        """Fallback when global hotkeys are unavailable: shortcuts work while this window is focused."""
        for s in self._local_shortcuts:
            s.setEnabled(False)
            s.deleteLater()
        self._local_shortcuts = []
        if self.ctx.global_hotkeys:
            return
        for action in HOTKEY_ACTIONS:
            combo = normalize_combo(getattr(self.ctx.settings.hotkeys, action))
            seq = QKeySequence("+".join(part.capitalize() if len(part) > 1 else part for part in combo.split("+")))
            sc = QShortcut(seq, self, context=Qt.ApplicationShortcut)
            sc.activated.connect(lambda a=action: self._local(a))
            self._local_shortcuts.append(sc)

    def _local(self, action: str) -> None:
        if action == "stop":
            self.ctx.engine.emergency_stop()
        self.on_hotkey(action)

    def on_hotkey(self, action: str) -> None:
        if action == "start":
            self.start_automation()
        elif action == "pause":
            self.ctx.engine.toggle_pause()
        elif action == "stop":
            self.ctx.engine.emergency_stop()  # idempotent; already done on the hotkey thread
        elif action == "overlay":
            self.vision.overlay_chk.setChecked(not self.vision.overlay_chk.isChecked())
        elif action == "calibrate":
            self.toggle_calibration()
        elif action == "snapshot":
            self.diagnostic_snapshot()

    # ------------------------------------------------------------------ actions
    def ensure_acknowledged(self) -> bool:
        if self.ctx.settings.risk_acknowledged:
            return True
        dlg = RiskDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.ctx.settings.risk_acknowledged = True
            self.ctx.save_settings()
            return True
        return False

    def start_automation(self) -> None:
        if self.calibration is not None:
            return
        if not self.ensure_acknowledged():
            return
        if self.ctx.engine.status == Status.PAUSED:
            self.ctx.engine.resume()
            return
        self.ctx.save_profile()
        self.ctx.engine.start_automation()

    def emergency_stop(self) -> None:
        self.ctx.engine.emergency_stop()

    def set_overlay(self, on: bool) -> None:
        self.ctx.settings.overlay_enabled = on
        if on:
            if self.ctx.engine.status == Status.STOPPED:
                self.ctx.engine.start_vision()
            self.overlay.show()
        else:
            self.overlay.hide()

    def toggle_calibration(self) -> None:
        if self.calibration is not None:
            self.calibration.close()
            return
        eng = self.ctx.engine
        if eng.status == Status.RUNNING:
            eng.pause()
        try:
            frame = eng.capture_full_frame()
        except CaptureError as exc:
            QMessageBox.warning(self, "Calibration", f"Could not capture the game: {exc}\n\nOpen Roblox (windowed or "
                                                     "borderless) and check the window title in Settings.")
            return
        hidden_overlay = self.overlay.isVisible()
        self.overlay.hide()
        game_rect = None if eng.simulated or self.ctx.settings.capture.mode == "simulation" else \
            (*frame.screen_origin, *frame.client_size)
        from fischmacro.diagnostics.snapshot import annotate
        image = annotate(frame, self.ctx.profile, None) if frame.origin != (0, 0) else frame.image
        self.calibration = CalibrationWindow(image, self.ctx.profile, frame.client_size[1], self._calibration_saved,
                                             game_rect)

        def closed(saved):
            self.calibration = None
            if hidden_overlay:
                self.overlay.show()
            log.info("Calibration %s", "saved" if saved else "cancelled")
        self.calibration.closed.connect(closed)
        self.calibration.show()
        self.calibration.raise_()
        self.calibration.activateWindow()

    def _calibration_saved(self) -> None:
        self.ctx.save_profile()
        self.ctx.engine.vision.reset_background()
        self.vision.on_profile_switched()
        self.statusBar().showMessage("Calibration saved to profile '%s'" % self.ctx.profile.name, 5000)

    def diagnostic_snapshot(self) -> None:
        eng = self.ctx.engine
        snap = eng.snapshot()
        try:
            if snap.preview is not None and eng.status != Status.STOPPED:
                frame, obs = snap.preview, snap.preview_obs
            else:
                frame = eng.capture_full_frame()
                obs = eng.vision.process(frame)
            folder = save_snapshot(frame, self.ctx.profile, obs, note="manual")
        except (CaptureError, OSError) as exc:
            QMessageBox.warning(self, "Snapshot", f"Snapshot failed: {exc}")
            return
        self.statusBar().showMessage(f"Snapshot saved: {folder}", 8000)
        if self.isActiveWindow():
            box = QMessageBox(self)
            box.setWindowTitle("Diagnostic snapshot")
            box.setText(f"Saved raw and annotated screenshots with a detection report to:\n{folder}")
            open_btn = box.addButton("Open folder", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Ok)
            box.exec()
            if box.clickedButton() is open_btn:
                open_folder(folder)

    def on_profile_switched(self) -> None:
        self._fill_profiles()
        self.automation.on_profile_switched()
        self.vision.on_profile_switched()
        self.profiles.on_profile_switched()
        self.hotkeys.update_view()

    # ------------------------------------------------------------------ polling
    def poll(self) -> None:
        eng = self.ctx.engine
        s = eng.snapshot()
        events = eng.drain_events()
        if events:
            self.ctx.activity.extend(events)
            self.dashboard.add_events(events)
            self._notify_events(events)
            if any(k in ("cycle", "error") for _, k, _ in events):
                self._stats_dirty = True
        self.dashboard.refresh(s)
        self.vision.refresh(s, self.stack.currentWidget() is self.vision)
        if self.stack.currentWidget() is self.logs:
            self.logs.poll_log()
        if self.overlay.isVisible():
            game_rect = (*s.preview.screen_origin, *s.preview.client_size) if s.preview is not None else None
            self.overlay.update_state(s, self.ctx.profile, game_rect)
        locked = s.status in (Status.RUNNING, Status.PAUSED)
        self.profiles.set_locked(locked)
        self.profile_combo.setEnabled(not locked)
        self.tray.update(s.status, s.session.catches)
        col = STATUS_COLORS[s.status.value]
        self.side_status.setText(s.status.value)
        self.side_status.setStyleSheet(f"color: {col};")
        hk = self.ctx.settings.hotkeys
        self.side_hint.setText(f"{hk.start.upper()} start · {hk.pause.upper()} pause · {hk.stop.upper()} stop")
        self.sb_profile.setText(f"Profile: {self.ctx.profile.name}")
        mode = self.ctx.settings.capture.mode
        self.sb_capture.setText(f"Capture: {mode}" + ("" if s.status == Status.STOPPED or mode == "simulation" else
                                                     (" (window found)" if s.window_found else " (window NOT found)")))
        self.sb_fps.setText(f"{s.fps:.0f} FPS" if s.status != Status.STOPPED else "Vision idle")
        self.sb_keys.setText("Global hotkeys on" if self.ctx.global_hotkeys else "Hotkeys: app window only")
        self._tick += 1
        if self._stats_dirty and self._tick % 15 == 0:
            self._stats_dirty = False
            self.logs.refresh_stats()

    # ------------------------------------------------------------------ shutdown
    def detach(self) -> None:
        """Disconnect from the shared context before this window is replaced (theme change)."""
        self.rebuilding = True
        for sig, slot in ((self.ctx.hotkey, self.on_hotkey), (self.ctx.profile_switched, self.on_profile_switched),
                          (self.ctx.settings_changed, self._on_settings_changed)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self.timer.stop()
        self.stats_timer.stop()
        self.tray.set_visible(False)
        self.overlay.close()

    def closeEvent(self, e):
        if self.rebuilding:
            e.accept()
            return
        eng = self.ctx.engine
        if eng.status in (Status.RUNNING, Status.PAUSED) and self.ctx.settings.startup.confirm_exit_while_running:
            if QMessageBox.question(self, APP_NAME, "Automation is running. Stop it and exit?") != QMessageBox.Yes:
                e.ignore()
                return
        if eng.status in (Status.RUNNING, Status.PAUSED):
            eng.stop_automation("application closed")
        if self.calibration is not None:
            self.calibration.close()
        self.overlay.close()
        self.timer.stop()
        self.tray.set_visible(False)
        self.ctx.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.ctx.shutdown()
        e.accept()
