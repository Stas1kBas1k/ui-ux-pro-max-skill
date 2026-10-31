"""About: version, what the app does and does not do, credits."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from fischmacro import APP_NAME, __version__
from fischmacro.ui.logo import logo_pixmap
from fischmacro.ui.widgets import label, page_header


class AboutPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 12, 12, 12)
        v.setSpacing(12)
        v.setAlignment(Qt.AlignTop)
        v.addWidget(page_header("About", f"{APP_NAME} {__version__}"))
        art = QLabel()
        art.setPixmap(logo_pixmap(96))
        v.addWidget(art)
        for t in ("An external helper for Roblox Fisch: it looks at the screen and sends normal mouse and keyboard "
                  "input, like a player would. It never reads or changes game memory, never injects code and never "
                  "talks to Roblox servers.",
                  "Everything runs on your PC. Settings, profiles and logs are saved next to the app. Nothing is sent "
                  "anywhere unless you turn on Discord alerts or the AI assistant.",
                  "Updates: download the latest build from the project's GitHub Actions page."):
            v.addWidget(label(t, "muted", wrap=True))
