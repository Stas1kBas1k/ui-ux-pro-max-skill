from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from fischmacro.input.hotkeys import HotkeyError, find_conflicts, normalize_combo
from fischmacro.profiles.schema import HOTKEY_ACTIONS, HotkeyConfig
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import Card, label, page_header

_QT_NAMES = {
    Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Escape: "esc", Qt.Key_Space: "space", Qt.Key_Tab: "tab",
    Qt.Key_Backspace: "backspace", Qt.Key_Insert: "insert", Qt.Key_Delete: "delete", Qt.Key_Home: "home",
    Qt.Key_End: "end", Qt.Key_PageUp: "page_up", Qt.Key_PageDown: "page_down", Qt.Key_Pause: "pause",
    Qt.Key_ScrollLock: "scroll_lock", Qt.Key_Print: "print_screen", Qt.Key_Up: "up", Qt.Key_Down: "down",
    Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Backslash: "\\",
}


def qt_key_to_name(key: int) -> str | None:
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f"f{key - Qt.Key_F1 + 1}"
    if key in _QT_NAMES:
        return _QT_NAMES[key]
    text = QKeySequence(key).toString().lower()
    return text if len(text) == 1 else None


class KeyCaptureButton(QPushButton):
    """Click, then press the desired key combination."""

    captured = Signal(str)
    capturing = Signal(bool)

    def __init__(self, combo: str):
        super().__init__(combo.upper())
        self.combo = combo
        self.setCheckable(True)
        self.setMinimumWidth(160)
        self.toggled.connect(self._on_toggle)

    def _on_toggle(self, on: bool) -> None:
        self.capturing.emit(on)
        self.setText("Press keys..." if on else self.combo.upper())
        if on:
            self.grabKeyboard()
        else:
            self.releaseKeyboard()

    def keyPressEvent(self, e):
        if not self.isChecked():
            return super().keyPressEvent(e)
        key = e.key()
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return
        if key == Qt.Key_Escape:
            self.setChecked(False)
            return
        name = qt_key_to_name(key)
        if not name:
            return
        mods = []
        m = e.modifiers()
        if m & Qt.ControlModifier:
            mods.append("ctrl")
        if m & Qt.AltModifier:
            mods.append("alt")
        if m & Qt.ShiftModifier:
            mods.append("shift")
        try:
            combo = normalize_combo("+".join(mods + [name]))
        except HotkeyError:
            return
        self.combo = combo
        self.setChecked(False)
        self.captured.emit(combo)

    def set_combo(self, combo: str) -> None:
        self.combo = combo
        self.setText(combo.upper())


class HotkeysPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(page_header("Hotkeys", "Global shortcuts work while Roblox is the active window. Each press "
                                              "fires once; holding a key does not repeat the action."))
        self.status = label("", "banner", wrap=True)
        root.addWidget(self.status)
        card = Card("Shortcuts", "Click a shortcut, then press the new key or combination (Esc cancels).")
        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(16)
        self.buttons: dict[str, KeyCaptureButton] = {}
        defaults = HotkeyConfig()
        for row, (action, text) in enumerate(HOTKEY_ACTIONS.items()):
            grid.addWidget(label(text), row, 0)
            b = KeyCaptureButton(getattr(ctx.settings.hotkeys, action))
            b.captured.connect(lambda combo, a=action: self._set(a, combo))
            b.capturing.connect(self._capturing)
            grid.addWidget(b, row, 1)
            reset = QPushButton(icon("reset"), "")
            reset.setObjectName("ghost")
            reset.setToolTip(f"Reset to {getattr(defaults, action).upper()}")
            reset.clicked.connect(lambda _=False, a=action: self._set(a, getattr(HotkeyConfig(), a)))
            grid.addWidget(reset, row, 2)
            self.buttons[action] = b
        grid.setColumnStretch(3, 1)
        card.add(grid)
        self.conflicts = label("", "bannerWarn", wrap=True)
        card.add(self.conflicts)
        root.addWidget(card)

        act = Card("Active shortcuts")
        self.active = label("", "muted", wrap=True)
        self.active.setTextFormat(Qt.RichText)
        act.add(self.active)
        h = QHBoxLayout()
        reset_all = QPushButton(icon("reset"), "  Restore defaults")
        reset_all.clicked.connect(self._reset_all)
        h.addWidget(reset_all)
        h.addStretch(1)
        act.add(h)
        root.addWidget(act)
        root.addStretch(1)
        self.update_view()

    def _capturing(self, on: bool) -> None:
        # Do not trigger actions while the user is choosing a key.
        self.ctx.hotkeys.enabled = not on

    def _set(self, action: str, combo: str) -> None:
        setattr(self.ctx.settings.hotkeys, action, combo)
        self.buttons[action].set_combo(combo)
        self.ctx.apply_hotkeys()
        self.update_view()

    def _reset_all(self) -> None:
        for a in HOTKEY_ACTIONS:
            self._set(a, getattr(HotkeyConfig(), a))

    def update_view(self) -> None:
        b = self.ctx.settings.hotkeys.as_dict()
        dup = find_conflicts(b)
        warnings = [f"{combo.upper()} is assigned to: {', '.join(HOTKEY_ACTIONS[a] for a in acts)} "
                    f"- only the first one will work." for combo, acts in dup.items()]
        warnings += self.ctx.hotkey_warnings()
        self.conflicts.setVisible(bool(warnings))
        self.conflicts.setText("\n".join(warnings))
        for action, btn in self.buttons.items():
            bad = any(action in acts for acts in dup.values())
            btn.setStyleSheet(f"border-color: {C['warning']};" if bad else "")
        rows = []
        for action, text in HOTKEY_ACTIONS.items():
            rows.append(f"<b style='color:{C['text']}'>{b[action].upper()}</b> &nbsp; {text}")
        self.active.setText("<br>".join(rows))
        if self.ctx.global_hotkeys:
            self.status.setObjectName("banner")
            self.status.setText("Global hotkeys are active and work while Roblox is focused.")
        else:
            self.status.setObjectName("bannerWarn")
            self.status.setText("Global hotkeys are unavailable on this system, so shortcuts only work while this "
                                "window is focused. On Windows, check that security software is not blocking "
                                "keyboard hooks.")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
