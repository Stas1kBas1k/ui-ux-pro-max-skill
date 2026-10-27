from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QMessageBox, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from fischmacro.automation.modules import REGISTRY, ModuleHost
from fischmacro.profiles.rod_presets import PRESETS, apply_preset
from fischmacro.ui.widgets import Card, ConfigForm, ModuleForm, exp_badge, label, page_header


def scroll(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(inner)
    return sa


class AutomationPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)
        root.addWidget(page_header("Automation", "Fishing modules, casting, shaking, reeling, recovery and timeouts. "
                                                 "Changes apply immediately and are saved to the active profile."))
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.build()

    def _section(self, title: str, subtitle: str, target, **kw) -> Card:
        card = Card(title, subtitle)
        form = ConfigForm(target, **kw)
        form.changed.connect(self.ctx.profile_edited)
        card.add(form)
        self._forms.append(form)
        return card

    def build(self) -> None:
        self.tabs.clear()
        self._forms = []
        p = self.ctx.profile

        def page(*cards) -> QWidget:
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 12, 8, 12)
            v.setSpacing(14)
            for c in cards:
                v.addWidget(c)
            v.addStretch(1)
            return scroll(w)

        self.tabs.addTab(page(self._section(
            "Casting", "Hold to charge, release on a full power bar ('perfect') or after a fixed time ('timed'). "
                       "If the power bar is never detected the timed hold is used as a fallback.", p.casting)), "Casting")
        self.tabs.addTab(page(self._section(
            "Shake", "Click mode finds shake buttons by colour (or a captured template) and clicks each stable "
                     "target once. Navigation mode uses Roblox UI navigation keys instead and needs no detection.",
            p.shake)), "Shake")
        self.tabs.addTab(page(self._section(
            "Reel controller", "PD controller with velocity feed-forward. Tune per rod: hover duty is the fraction of time "
                               "the mouse must be held to keep the bar still; raise Kp for faster fish, raise Kd if the "
                               "bar overshoots.", p.reel)), "Reeling")
        self.tabs.addTab(page(self._section(
            "Timeouts & recovery", "When a stage takes too long the controller releases all input, optionally "
                                   "re-equips, and tries again. Too many recoveries in a row stop automation.",
            p.timing)), "Recovery && timeouts")
        rod = self._section("Rod & equipment", "Rod-specific settings live in profiles: one profile per rod (and per "
                                               "skin). With a 'Rod name' watcher they are picked automatically.",
                            p.equipment)
        h = QHBoxLayout()
        self.preset_combo = QComboBox()
        for pr in PRESETS:
            self.preset_combo.addItem(pr.name)
        apply_btn = QPushButton("Apply rod preset")
        apply_btn.clicked.connect(self._apply_preset)
        h.addWidget(label("Rod preset", "muted"))
        h.addWidget(self.preset_combo)
        h.addWidget(apply_btn)
        h.addStretch(1)
        rod.add(h)
        self.preset_note = label("", "faint", wrap=True)
        rod.add(self.preset_note)
        self.preset_combo.currentIndexChanged.connect(lambda i: self.preset_note.setText(PRESETS[i].note))
        self.preset_note.setText(PRESETS[0].note)
        self.tabs.addTab(page(rod), "Rod && equipment")
        mini = self._section("Rod minigame", "For rods with their own minigame. The catch bar keeps following the fish "
                                             "unless you switch that off. Calibrate the 'Rod minigame area' and "
                                             "'target sign' regions and sample their colours in the calibration tool.",
                             p.minigame)
        self.tabs.addTab(page(mini), "Rod minigame")

        host = ModuleHost(p.modules)  # fills defaults into the profile's module settings
        mod_cards = []
        for mid, cls in REGISTRY.items():
            m = host.modules[mid]
            card = Card(cls.name, cls.description)
            if cls.experimental:
                card.head.addWidget(exp_badge())
            toggle = QCheckBox("Enabled")
            toggle.setChecked(m.enabled)

            def on_toggle(v, m=m):
                m.settings["enabled"] = bool(v)
                self.ctx.profile_edited()
            toggle.toggled.connect(on_toggle)
            card.head.addWidget(toggle)
            form = ModuleForm(m)
            form.changed.connect(self.ctx.profile_edited)
            card.add(form)
            mod_cards.append(card)
        note = Card("Adding modules", "")
        note.add(label("Modules can only send input between catches (safe points), never during a minigame. "
                       "New Fisch mechanics can be added as modules - see 'Extending' in the README.", "muted", wrap=True))
        mod_cards.append(note)
        self.tabs.addTab(page(*mod_cards), "Modules")

    def _apply_preset(self) -> None:
        pr = PRESETS[self.preset_combo.currentIndex()]
        changed = apply_preset(self.ctx.profile, pr)
        self.ctx.save_profile()
        self.on_profile_switched()
        QMessageBox.information(self, "Rod preset", f"Applied '{pr.name}' to profile '{self.ctx.profile.name}'"
                                + (f": {', '.join(changed)}" if changed else " (already set)."))

    def on_profile_switched(self) -> None:
        idx = self.tabs.currentIndex()
        self.build()
        self.tabs.setCurrentIndex(max(0, idx))
