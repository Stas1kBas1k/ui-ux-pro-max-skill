"""Simple, consistent building blocks for the main pages.

AddonCard  - icon, title, one-line description, square checkbox and an expand chevron
RowGroup   - a rounded box of label/control rows separated by hairlines
DotCombo   - a dropdown whose entries carry a small coloured dot
NumberBox  - a compact number field
ChipCatalogue - search box + Add button over a wrapping list of selectable chips
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QMenu, QPushButton, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C, rgba


def dot_icon(color: str | None, size: int = 10, checked: bool = False) -> QIcon:
    """A filled circle (or a check mark in that colour when ``checked``)."""
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor(color or C["faint"])
    if checked:
        pen = QPen(col, 2.2 * scale * size / 12)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        s = size * scale
        p.drawPolyline([QPoint(int(s * .18), int(s * .52)), QPoint(int(s * .42), int(s * .76)),
                        QPoint(int(s * .84), int(s * .26))])
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(1, 1, size * scale - 2, size * scale - 2)
    p.end()
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)


class SquareCheck(QCheckBox):
    """Rounded square checkbox (the switch style is used elsewhere)."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("square")
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)


class NumberBox(QSpinBox):
    def __init__(self, value: int, lo: int = 0, hi: int = 100, suffix: str = "", step: int = 1, parent=None):
        super().__init__(parent)
        self.setObjectName("number")
        self.setRange(lo, hi)
        self.setSingleStep(step)
        self.setValue(int(value))
        if suffix:
            self.setSuffix(suffix)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedWidth(88)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, e):  # noqa: N802 - scrolling the page must not change values
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class DotCombo(QComboBox):
    """Dropdown of (name, colour) entries; colour None shows no dot."""

    def __init__(self, items: Iterable[tuple[str, str | None]], current: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("dotCombo")
        self.setIconSize(QSize(10, 10))
        self.setMinimumWidth(190)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        for name, color in items:
            self.addItem(dot_icon(color) if color else QIcon(), name)
        if current:
            i = self.findText(current)
            if i >= 0:
                self.setCurrentIndex(i)

    def wheelEvent(self, e):  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class RowGroup(QFrame):
    """A rounded inner panel holding rows: label (+ hint) on the left, a control on the right."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rowGroup")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(0)
        self._rows = 0

    def add_row(self, title: str, hint: str = "", control: QWidget | None = None,
                icon_name: str | None = None) -> QWidget:
        if self._rows:
            sep = QFrame()
            sep.setObjectName("rowSep")
            self.v.addWidget(sep)
        self._rows += 1
        row = QWidget()
        row.setObjectName("row")
        h = QHBoxLayout(row)
        h.setContentsMargins(16, 11, 12, 11)
        h.setSpacing(14)
        if icon_name:
            ic = QLabel()
            ic.setPixmap(icon(icon_name, C["muted"], 17).pixmap(17, 17))
            ic.setFixedWidth(20)
            h.addWidget(ic, 0, Qt.AlignVCenter)
            h.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        t.setObjectName("rowTitle")
        col.addWidget(t)
        if hint:
            s = QLabel(hint)
            s.setObjectName("rowHint")
            s.setWordWrap(True)
            col.addWidget(s)
        h.addLayout(col, 1)
        if control is not None:
            h.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.v.addWidget(row)
        return row

    def add_value(self, title: str, hint: str = "", icon_name: str | None = None) -> QLabel:
        """A read-only readout ('---' until something is known)."""
        val = QLabel("---")
        val.setObjectName("rowValue")
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val.setMinimumWidth(90)
        self.add_row(title, hint, val, icon_name)
        return val


class StatStrip(QFrame):
    """A row of big numbers with small captions, split by hairlines."""

    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("rowGroup")
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 12, 6, 12)
        h.setSpacing(0)
        self.values: dict[str, QLabel] = {}
        for i, (key, caption) in enumerate(items):
            if i:
                sep = QFrame()
                sep.setObjectName("vSep")
                h.addWidget(sep)
            col = QVBoxLayout()
            col.setSpacing(2)
            v = QLabel("-")
            v.setObjectName("stripValue")
            v.setAlignment(Qt.AlignCenter)
            c = QLabel(caption)
            c.setObjectName("rowHint")
            c.setAlignment(Qt.AlignCenter)
            col.addWidget(v)
            col.addWidget(c)
            h.addLayout(col, 1)
            self.values[key] = v

    def set(self, key: str, text: str, color: str | None = None) -> None:
        lab = self.values[key]
        lab.setText(text)
        lab.setStyleSheet(f"color: {color};" if color else "")


def section_title(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("sectionTitle")
    return lab


class AddonCard(QFrame):
    toggled = Signal(bool)

    def __init__(self, icon_name: str, title: str, description: str, color: str | None = None,
                 checked: bool | None = False, expanded: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("addon")
        color = color or C["primary"]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QWidget()
        self.header.setObjectName("addonHead")
        self.header.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self.header)
        h.setContentsMargins(16, 14, 14, 14)
        h.setSpacing(14)
        tile = QLabel()
        tile.setObjectName("addonIcon")
        tile.setFixedSize(42, 42)
        tile.setAlignment(Qt.AlignCenter)
        tile.setStyleSheet(f"background: {rgba(color, 0.16)}; border-radius: 11px;")
        tile.setPixmap(icon(icon_name, color, 22).pixmap(22, 22))
        h.addWidget(tile)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("addonTitle")
        d = QLabel(description)
        d.setObjectName("addonDesc")
        d.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(d)
        h.addLayout(col, 1)
        self.check: SquareCheck | None = None
        if checked is not None:
            self.check = SquareCheck(checked)
            self.check.setToolTip("Turn on / off")
            self.check.toggled.connect(self.toggled.emit)
            h.addWidget(self.check)
        self.chevron = QPushButton()
        self.chevron.setObjectName("chevron")
        self.chevron.setFixedSize(30, 30)
        self.chevron.setCursor(Qt.PointingHandCursor)
        self.chevron.setToolTip("Show settings")
        self.chevron.clicked.connect(self.toggle_expanded)
        h.addWidget(self.chevron)
        outer.addWidget(self.header)

        self.body = QWidget()
        self.body.setObjectName("addonBody")
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(16, 4, 16, 16)
        self.lay.setSpacing(8)
        outer.addWidget(self.body)
        self.header.mousePressEvent = lambda e: self.toggle_expanded()
        self.set_expanded(expanded)

    @property
    def enabled_value(self) -> bool:
        return bool(self.check and self.check.isChecked())

    def set_expanded(self, on: bool) -> None:
        self.body.setVisible(on)
        self.chevron.setIcon(icon("chevron-down" if on else "chevron-right", C["muted"], 18))
        self.setProperty("open", on)

    def toggle_expanded(self) -> None:
        self.set_expanded(not self.body.isVisible())

    def section(self, title: str) -> RowGroup:
        self.lay.addSpacing(6)
        self.lay.addWidget(section_title(title))
        g = RowGroup()
        self.lay.addWidget(g)
        return g

    def note(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("rowHint")
        lab.setWordWrap(True)
        self.lay.addWidget(lab)
        return lab


# --------------------------------------------------------------------------- chips

class FlowLayout(QLayout):
    """Wraps child widgets onto new lines like text."""

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 - Qt API
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, w):  # noqa: N802
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):  # noqa: N802
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect: QRect, test: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for it in self._items:
            if it.widget() is not None and not it.widget().isVisibleTo(it.widget().parentWidget()):
                continue
            hint = it.sizeHint()
            nx = x + hint.width() + self._sp
            if nx - self._sp > rect.right() and line > 0:
                x, y = rect.x(), y + line + self._sp
                nx, line = x + hint.width() + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x, line = nx, max(line, hint.height())
        return y + line - rect.y()


class Chip(QPushButton):
    def __init__(self, name: str, color: str | None, custom: bool = False, parent=None):
        super().__init__(" " + name, parent)
        self.setObjectName("chip")
        self.name, self.color, self.custom = name, color, custom
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(11, 11))
        self.toggled.connect(self._refresh)
        self._refresh(False)

    def _refresh(self, on: bool) -> None:
        self.setIcon(dot_icon(self.color, 11, checked=on))


class ChipCatalogue(QWidget):
    """Pick names from a catalogue; type a new name and press Add for anything missing."""

    changed = Signal()

    def __init__(self, catalogue: list[tuple[str, str]], selected: Iterable[str], custom: Iterable[str],
                 placeholder: str = "Search the catalogue, or type a name to add", parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search", C["faint"], 16), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._add_typed)
        self.add_btn = QPushButton(icon("plus", C["on_primary"], 16), " Add")
        self.add_btn.setObjectName("primary")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._add_typed)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.add_btn)
        v.addLayout(bar)
        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("rowHint")
        v.addWidget(self.count_lbl)
        self.area = QWidget()
        self.flow = FlowLayout(self.area, 8)
        v.addWidget(self.area)
        self.empty = QLabel("Nothing matches. Press Add to watch for it anyway.")
        self.empty.setObjectName("rowHint")
        v.addWidget(self.empty)
        self.chips: dict[str, Chip] = {}
        sel = {s.lower() for s in selected}
        for name, color in catalogue:
            self._make(name, color, False, name.lower() in sel)
        for name in custom:
            if name.lower() not in {k.lower() for k in self.chips}:
                self._make(name, None, True, True)
        self._filter("")

    def _make(self, name: str, color: str | None, custom: bool, checked: bool) -> Chip:
        chip = Chip(name, color, custom)
        chip.setChecked(checked)
        chip.toggled.connect(lambda _=False: self._changed())
        if custom:
            chip.setContextMenuPolicy(Qt.CustomContextMenu)
            chip.customContextMenuRequested.connect(lambda _p, c=chip: self._chip_menu(c))
            chip.setToolTip("Added by you - right-click to remove")
        self.chips[name] = chip
        self.flow.addWidget(chip)
        return chip

    def _chip_menu(self, chip: Chip) -> None:
        m = QMenu(self)
        m.addAction("Remove", lambda: self.remove(chip.name))
        m.exec(chip.mapToGlobal(chip.rect().bottomLeft()))

    def remove(self, name: str) -> None:
        chip = self.chips.pop(name, None)
        if chip is not None:
            self.flow.removeWidget(chip)
            chip.deleteLater()
            self._changed()

    def _add_typed(self) -> None:
        name = " ".join(self.search.text().split())
        if not name:
            return
        existing = next((k for k in self.chips if k.lower() == name.lower()), None)
        if existing:
            self.chips[existing].setChecked(True)
        else:
            self._make(name, None, True, True)
            self._changed()
        self.search.clear()

    def _filter(self, text: str) -> None:
        t = text.strip().lower()
        shown = 0
        for name, chip in self.chips.items():
            vis = not t or t in name.lower()
            chip.setVisible(vis)
            shown += vis
        self.empty.setVisible(shown == 0)
        self.add_btn.setEnabled(bool(t))
        self.flow.invalidate()
        self.area.updateGeometry()
        self._count()

    def _count(self) -> None:
        n = len(self.selected())
        self.count_lbl.setText(f"{n} selected" if n else "Nothing selected yet - click the ones you want to be told about")

    def _changed(self) -> None:
        self._count()
        self.changed.emit()

    def selected(self) -> list[str]:
        return [n for n, c in self.chips.items() if c.isChecked() and not c.custom]

    def custom(self) -> list[str]:
        return [n for n, c in self.chips.items() if c.custom]

    def custom_selected(self) -> list[str]:
        return [n for n, c in self.chips.items() if c.custom and c.isChecked()]


def wide(widget: QWidget, width: int = 220) -> QWidget:
    widget.setMinimumWidth(width)
    widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return widget


def bind_check(box: QCheckBox, setter: Callable[[bool], None]) -> QCheckBox:
    box.toggled.connect(setter)
    return box
