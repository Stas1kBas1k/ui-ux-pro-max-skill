"""The app logo, drawn from one SVG so it stays sharp at every size (sidebar, splash, window icon)."""
from __future__ import annotations

from functools import lru_cache

LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#1B1636"/><stop offset="1" stop-color="#090B14"/>
    </linearGradient>
    <linearGradient id="ink" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#A592FF"/><stop offset="1" stop-color="#3BE0F5"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="16" fill="url(#bg)"/>
  <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="15.25" fill="none" stroke="url(#ink)" stroke-opacity=".55" stroke-width="1.5"/>
  <path d="M32 6v12" stroke="url(#ink)" stroke-width="2" stroke-linecap="round" stroke-opacity=".7"/>
  <path d="M11 36C20 21 38 19 52 42M11 36C20 50 38 51 52 28" fill="none" stroke="url(#ink)" stroke-width="4.4"
        stroke-linecap="round"/>
  <circle cx="22.5" cy="33" r="2.6" fill="#3BE0F5"/>
  <circle cx="32" cy="19.5" r="2" fill="#A592FF"/>
</svg>"""


@lru_cache(maxsize=16)
def logo_pixmap(size: int = 64):
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(LOGO_SVG.encode()))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def logo_icon():
    from PySide6.QtGui import QIcon
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(logo_pixmap(s))
    return ic


def splash_pixmap():
    """Loading screen: the logo and the name on the app's dark background."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap

    from fischmacro import APP_NAME, __version__
    w, h = 460, 260
    pm = QPixmap(w, h)
    pm.fill(QColor("#090B12"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor(124, 92, 255, 40))
    g.setColorAt(1, QColor(59, 224, 245, 18))
    p.fillRect(pm.rect(), g)
    p.drawPixmap(int(w / 2 - 48), 46, logo_pixmap(96))
    f = QFont()
    f.setPointSize(17)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#EEF0F7"))
    p.drawText(QRectF(0, 156, w, 32), Qt.AlignCenter, APP_NAME)
    f.setPointSize(9)
    f.setBold(False)
    p.setFont(f)
    p.setPen(QColor("#8C93AD"))
    p.drawText(QRectF(0, 190, w, 22), Qt.AlignCenter, f"v{__version__} · loading...")
    p.end()
    return pm
