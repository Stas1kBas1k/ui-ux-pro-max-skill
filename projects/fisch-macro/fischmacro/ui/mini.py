"""The small fishing card shown instead of the main window while fishing."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from fischmacro.automation.engine import EngineSnapshot, Status
from fischmacro.ui.icons import icon
from fischmacro.ui.pages.dashboard import fmt_duration
from fischmacro.ui.pages.fishing import PHASES
from fischmacro.ui.theme import C, STATUS_COLORS


class MiniWindow(QWidget):
    expand_requested = Signal()
    pause_requested = Signal()
    stop_requested = Signal()

    def __init__(self, on_top: bool = True, opacity: float = 0.94):
        flags = Qt.Tool | Qt.FramelessWindowHint
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(opacity)
        self.setWindowTitle("Fisch Macro")
        self._drag: QPoint | None = None
        card = QFrame(self)
        card.setObjectName("miniCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 10, 10, 12)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.dot = QLabel("●")
        self.status = QLabel("Stopped")
        self.status.setObjectName("rowTitle")
        head.addWidget(self.dot)
        head.addWidget(self.status, 1)
        for name, tip, sig in (("pause", "Pause / resume (F7)", self.pause_requested),
                               ("stop", "Stop (F8)", self.stop_requested),
                               ("layout-dashboard", "Open the full window", self.expand_requested)):
            b = QPushButton(icon(name, C["muted"], 15), "")
            b.setObjectName("chevron")
            b.setFixedSize(28, 28)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(sig.emit)
            head.addWidget(b)
            if name == "pause":
                self.pause_btn = b
        v.addLayout(head)
        row = QHBoxLayout()
        self.caught = QLabel("0")
        self.caught.setObjectName("stripValue")
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(self.caught)
        cap = QLabel("caught")
        cap.setObjectName("rowHint")
        col.addWidget(cap)
        row.addLayout(col)
        row.addSpacing(14)
        info = QVBoxLayout()
        info.setSpacing(1)
        self.phase = QLabel("---")
        self.line2 = QLabel("")
        self.line2.setObjectName("rowHint")
        self.line3 = QLabel("")
        self.line3.setObjectName("rowHint")
        for w in (self.phase, self.line2, self.line3):
            info.addWidget(w)
        row.addLayout(info, 1)
        v.addLayout(row)
        self.resize(300, 120)

    def refresh(self, s: EngineSnapshot) -> None:
        st = s.status
        col = STATUS_COLORS.get(st.value, C["faint"])
        self.dot.setStyleSheet(f"color: {col}; background: transparent;")
        self.status.setText(st.value)
        self.pause_btn.setIcon(icon("play" if st == Status.PAUSED else "pause", C["muted"], 15))
        sess = s.session
        self.caught.setText(str(sess.catches))
        self.phase.setText(PHASES.get(s.fsm_state, s.fsm_state.title()) if st != Status.STOPPED else "Stopped")
        rate = f"{sess.catches_per_hour:.0f}/h" if sess.catches_per_hour else "-/h"
        self.line2.setText(f"{sess.failures} lost · {rate}")
        self.line3.setText(fmt_duration(sess.active_seconds) + (f" · {s.message}" if s.message else ""))

    # drag anywhere to move
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag = None

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        self.expand_requested.emit()
