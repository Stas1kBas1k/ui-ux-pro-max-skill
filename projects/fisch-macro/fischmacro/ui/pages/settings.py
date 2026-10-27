from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget

from fischmacro import __version__, paths
from fischmacro.automation.engine import Status
from fischmacro.ui.fancy import ThemeCard
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import THEMES
from fischmacro.ui.widgets import Card, ConfigForm, label, page_header


def open_folder(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class SettingsPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        outer.addWidget(sa)
        body = QWidget()
        sa.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(page_header("Settings", "Application-wide settings. Game-specific tuning lives in profiles."))
        s = ctx.settings

        look = Card("Appearance", "Pick a theme and a text size that are comfortable for you. "
                                  "The window refreshes instantly; nothing else is interrupted.")
        gallery = QGridLayout()
        gallery.setSpacing(12)
        for i, name in enumerate(THEMES):
            card = ThemeCard(name, name == s.appearance.theme)
            card.clicked.connect(self._pick_theme)
            gallery.addWidget(card, i // 6, i % 6)
        gallery.setColumnStretch(6, 1)
        look.add(gallery)
        self.look_form = ConfigForm(s.appearance, exclude=["theme"])
        self.look_form.changed.connect(self._appearance_changed)
        look.add(self.look_form)
        root.addWidget(look)

        notes = Card("Notifications", "How Fisch Macro tells you about catches, reminders and problems.")
        f = ConfigForm(s.notifications)
        f.changed.connect(ctx.settings_edited)
        notes.add(f)
        root.addWidget(notes)

        cap = Card("Screen capture", "Where frames come from. Changing the source restarts the preview.")
        self.cap_form = ConfigForm(s.capture)
        self.cap_form.changed.connect(self._capture_changed)
        cap.add(self.cap_form)
        root.addWidget(cap)

        row = QHBoxLayout()
        row.setSpacing(14)
        perf = Card("Detection performance")
        f = ConfigForm(s.performance)
        f.changed.connect(ctx.settings_edited)
        perf.add(f)
        row.addWidget(perf, 1)
        inp = Card("Input timing", "Controller sensitivity is tuned per profile on the Automation page.")
        f = ConfigForm(s.input)
        f.changed.connect(self._input_changed)
        inp.add(f)
        row.addWidget(inp, 1)
        root.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(14)
        st = Card("Startup", "Automation itself never starts on launch.")
        f = ConfigForm(s.startup)
        f.changed.connect(ctx.settings_edited)
        st.add(f)
        row.addWidget(st, 1)
        lg = Card("Logging & diagnostics")
        f = ConfigForm(s.logging)
        f.changed.connect(ctx.settings_edited)
        lg.add(f)
        row.addWidget(lg, 1)
        root.addLayout(row)

        data = Card("Data locations", "Everything is stored locally in these folders.")
        grid = QGridLayout()
        for i, (name, path) in enumerate([("Data folder", paths.data_dir()), ("Profiles", paths.profiles_dir()),
                                          ("Logs", paths.logs_dir()), ("Diagnostics", paths.diagnostics_dir()),
                                          ("Templates", paths.templates_dir())]):
            grid.addWidget(label(name, "muted"), i, 0)
            grid.addWidget(label(str(path)), i, 1)
            b = QPushButton(icon("folder"), " Open")
            b.clicked.connect(lambda _=False, p=path: open_folder(p))
            grid.addWidget(b, i, 2)
        grid.setColumnStretch(1, 1)
        data.add(grid)
        root.addWidget(data)

        priv = Card("Privacy & safety")
        priv.add(label(
            "• Screenshots are processed in memory on this PC and are never uploaded.\n"
            "• No Roblox credentials, cookies or tokens are read or stored. No network access is made.\n"
            "• Input is sent with normal desktop mouse/keyboard events only: no memory reading, injection or "
            "anti-cheat bypass.\n"
            "• Third-party automation may break Roblox's or the game's rules and can put your account at risk. "
            "You use this tool at your own risk.", "muted", wrap=True))
        root.addWidget(priv)

        about = Card("About")
        about.add(label(f"Fisch Macro {__version__} - an independent, open tool. Not affiliated with Roblox or the "
                        f"Fisch developers.", "muted", wrap=True))
        h = QHBoxLayout()
        reset = QPushButton(icon("reset"), "  Reset application settings")
        reset.clicked.connect(self._reset)
        h.addWidget(reset)
        h.addStretch(1)
        about.add(h)
        root.addWidget(about)
        root.addStretch(1)

    def _pick_theme(self, name: str) -> None:
        if name != self.ctx.settings.appearance.theme:
            self.ctx.settings.appearance.theme = name
            self._appearance_changed("theme")

    def _appearance_changed(self, field: str = "") -> None:
        self.ctx.settings_edited(field)
        self.ctx.appearance_changed.emit()

    def _capture_changed(self, field: str) -> None:
        self.ctx.settings_edited(field)
        if field == "mode" or field == "window_title" or field == "monitor":
            if not self.ctx.restart_vision_if_idle():
                QMessageBox.information(self, "Capture", "The new capture source is used after automation stops.")

    def _input_changed(self, field: str) -> None:
        self.ctx.settings_edited(field)
        eng = self.ctx.engine
        i = self.ctx.settings.input
        eng.inputs.click_hold_ms, eng.inputs.key_hold_ms, eng.inputs.mouse_nudge = i.click_hold_ms, i.key_hold_ms, i.mouse_nudge
        eng.fsm.min_switch_interval = i.min_switch_interval_ms / 1000.0

    def _reset(self) -> None:
        if self.ctx.engine.status in (Status.RUNNING, Status.PAUSED):
            QMessageBox.warning(self, "Settings", "Stop automation first.")
            return
        if QMessageBox.question(self, "Reset", "Reset all application settings (not profiles) to defaults? "
                                               "The app will need to be restarted.") == QMessageBox.Yes:
            paths.settings_file().unlink(missing_ok=True)
            self.ctx.settings_store.save(type(self.ctx.settings)())
            QMessageBox.information(self, "Reset", "Settings reset. Restart the application to apply.")
