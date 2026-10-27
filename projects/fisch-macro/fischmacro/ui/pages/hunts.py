"""Hunts: pick the hunts and events you want to hear about."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from fischmacro.game_data import HUNTS
from fischmacro.ui.components import AddonCard, ChipCatalogue, SquareCheck
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import page_header


class HuntsPage(QWidget):
    def __init__(self, ctx, pick_region=None):
        super().__init__()
        self.ctx = ctx
        self.pick_region = pick_region
        h = ctx.settings.hunts
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 0)
        outer.setSpacing(12)
        outer.addWidget(page_header("Hunts", "Pick the hunts and events you care about. When one is announced "
                                             "on screen you get told, so you can come back and go for it."))
        inner = QWidget()
        inner.setMaximumWidth(860)
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 4, 10, 24)
        col.setSpacing(12)

        card = AddonCard("hunts", "Hunt catalogue", "Click a hunt to watch for it. Missing one? Type it and press Add.",
                         "#EF4444", None, expanded=True)
        card.chevron.hide()
        card.header.mousePressEvent = lambda e: None
        self.catalogue = ChipCatalogue(HUNTS, h.watched, h.custom, "Search the catalogue, or type a hunt to add")
        self.catalogue.changed.connect(self._save_chips)
        card.lay.addWidget(self.catalogue)
        col.addWidget(card)

        opts = AddonCard("alerts", "When a hunt shows up", "How you want to be told.", "#22D3EE", None, expanded=True)
        opts.chevron.hide()
        opts.header.mousePressEvent = lambda e: None
        g = opts.section("Notify")
        for attr, title, hint in (("discord", "Discord message", ""),
                                  ("toast", "Pop-up in this app", "A small notice in the corner"),
                                  ("pause", "Pause fishing", "Stops at the next safe moment so nothing is wasted")):
            box = SquareCheck(getattr(h, attr))
            box.toggled.connect(lambda v, a=attr: (setattr(h, a, v), self.ctx.settings_edited("hunts")))
            g.add_row(title, hint, box)
        self.discord_status = opts.note("")
        g = opts.section("Screen")
        pick = QPushButton(icon("crosshair", C["muted"], 16), " Pick on screen")
        pick.setCursor(Qt.PointingHandCursor)
        pick.clicked.connect(self._pick)
        g.add_row("Announcement area", "Where server messages appear (top of the screen by default)", pick)
        col.addWidget(opts)
        col.addStretch(1)

        wrap = QHBoxLayout()
        wrap.addWidget(inner, 10)
        wrap.addStretch(1)
        holder = QWidget()
        holder.setLayout(wrap)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(holder)
        outer.addWidget(sa, 1)
        self.refresh_discord()

    def _save_chips(self) -> None:
        h = self.ctx.settings.hunts
        h.watched = self.catalogue.selected() + self.catalogue.custom_selected()
        h.custom = self.catalogue.custom()
        self.ctx.settings_edited("hunts")

    def _pick(self) -> None:
        if not self.pick_region:
            return
        h = self.ctx.settings.hunts
        r = self.pick_region("Hunt announcements", "Drag a box over where server messages appear", h.region)
        if r is not None:
            h.region = r
            self.ctx.settings_edited("hunts")

    def refresh_discord(self) -> None:
        ok = self.ctx.engine.notifier.configured
        self.discord_status.setText("Discord is connected." if ok else
                                    "Discord is not set up yet - paste your webhook link in Settings > Notifications.")

    def showEvent(self, e):  # noqa: N802
        self.refresh_discord()
        super().showEvent(e)
