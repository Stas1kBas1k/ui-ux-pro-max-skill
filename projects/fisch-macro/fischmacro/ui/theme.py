"""Design tokens, colour themes and the application style sheet.

``C`` always holds the active palette. ``apply_theme`` swaps it in place; the
main window is then rebuilt so every widget picks the new colours up.
"""
from __future__ import annotations

THEMES: dict[str, dict[str, str]] = {
    "Midnight Violet": {
        "bg": "#111216", "sidebar": "#15161C", "surface": "#1A1B22", "card": "#1F2029", "card_hi": "#262733",
        "border": "#2C2D3A", "border_hi": "#3A3B4C", "text": "#ECEDF3", "muted": "#A2A8B8", "faint": "#6B7182",
        "primary": "#8B5CF6", "primary_hi": "#A78BFA", "on_primary": "#FFFFFF", "accent": "#22D3EE",
        "success": "#22C55E", "warning": "#F59E0B", "danger": "#EF4444", "danger_hi": "#F87171",
    },
    "Deep Ocean": {
        "bg": "#0B1220", "sidebar": "#0E1628", "surface": "#111B30", "card": "#14203A", "card_hi": "#1A2947",
        "border": "#1F3052", "border_hi": "#2B4170", "text": "#E8F1FF", "muted": "#9FB3D1", "faint": "#61779B",
        "primary": "#0EA5E9", "primary_hi": "#38BDF8", "on_primary": "#04121F", "accent": "#2DD4BF",
        "success": "#34D399", "warning": "#FBBF24", "danger": "#F43F5E", "danger_hi": "#FB7185",
    },
    "Abyss Emerald": {
        "bg": "#0D1210", "sidebar": "#101714", "surface": "#141D19", "card": "#18231F", "card_hi": "#1F2D27",
        "border": "#25362F", "border_hi": "#33493F", "text": "#E9F5EF", "muted": "#9DB7AA", "faint": "#62796E",
        "primary": "#10B981", "primary_hi": "#34D399", "on_primary": "#03140D", "accent": "#A3E635",
        "success": "#4ADE80", "warning": "#FACC15", "danger": "#F87171", "danger_hi": "#FCA5A5",
    },
    "Coral Reef": {
        "bg": "#151012", "sidebar": "#1A1316", "surface": "#20171B", "card": "#261C21", "card_hi": "#30232A",
        "border": "#3A2A31", "border_hi": "#4D3741", "text": "#F7ECEF", "muted": "#C1A7B0", "faint": "#82666F",
        "primary": "#FB7185", "primary_hi": "#FDA4AF", "on_primary": "#2A0A11", "accent": "#FDBA74",
        "success": "#4ADE80", "warning": "#FBBF24", "danger": "#EF4444", "danger_hi": "#F87171",
    },
    "Arctic Light": {
        "bg": "#F3F5F9", "sidebar": "#E9EDF4", "surface": "#FFFFFF", "card": "#FFFFFF", "card_hi": "#EEF1F7",
        "border": "#D8DEE9", "border_hi": "#C3CBDA", "text": "#141A26", "muted": "#4F5A6E", "faint": "#7C8699",
        "primary": "#6D28D9", "primary_hi": "#7C3AED", "on_primary": "#FFFFFF", "accent": "#0891B2",
        "success": "#15803D", "warning": "#B45309", "danger": "#DC2626", "danger_hi": "#B91C1C",
    },
    "High Contrast": {
        "bg": "#000000", "sidebar": "#000000", "surface": "#0A0A0A", "card": "#0F0F0F", "card_hi": "#1A1A1A",
        "border": "#FFFFFF", "border_hi": "#FFFFFF", "text": "#FFFFFF", "muted": "#E5E5E5", "faint": "#BDBDBD",
        "primary": "#FFE600", "primary_hi": "#FFF176", "on_primary": "#000000", "accent": "#00E5FF",
        "success": "#00FF7F", "warning": "#FFB300", "danger": "#FF4D4D", "danger_hi": "#FF8080",
    },
}
DEFAULT_THEME = "Midnight Violet"
TEXT_SIZES = {"Compact": 9.5, "Comfortable": 10.5, "Large": 12.0}

C: dict[str, str] = dict(THEMES[DEFAULT_THEME])
STATUS_COLORS: dict[str, str] = {}
EVENT_COLORS: dict[str, str] = {}
STATE = {"theme": DEFAULT_THEME, "base_pt": TEXT_SIZES["Comfortable"], "reduce_motion": False}

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", sans-serif'


def _derive() -> None:
    STATUS_COLORS.clear()
    STATUS_COLORS.update({"Running": C["success"], "Paused": C["warning"], "Monitoring": C["accent"],
                          "Stopped": C["faint"]})
    EVENT_COLORS.clear()
    EVENT_COLORS.update({
        "info": C["accent"], "cycle": C["success"], "cast": C["primary_hi"], "warning": C["warning"],
        "recovery": C["warning"], "error": C["danger"], "disconnect": C["danger"], "reminder": C["primary_hi"],
        "module": C["primary_hi"], "state": C["faint"], "shake": C["faint"],
    })


_derive()


def apply_theme(name: str, text_size: str = "Comfortable", reduce_motion: bool = False) -> None:
    C.clear()
    C.update(THEMES.get(name, THEMES[DEFAULT_THEME]))
    STATE.update(theme=name if name in THEMES else DEFAULT_THEME,
                 base_pt=TEXT_SIZES.get(text_size, TEXT_SIZES["Comfortable"]), reduce_motion=reduce_motion)
    _derive()


def is_light() -> bool:
    return STATE["theme"] == "Arctic Light"


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha})"


def pt(size_at_10: float) -> str:
    """Scale a point size defined for a 10 pt base to the active text size."""
    return f"{size_at_10 * STATE['base_pt'] / 10:.1f}pt"


def stylesheet() -> str:
    c = C
    sel = rgba(c["primary"], 0.22)
    return f"""
* {{ font-family: {FONT_STACK}; font-size: {pt(10)}; color: {c['text']}; }}
QMainWindow, QWidget#root {{ background: {c['bg']}; }}
QToolTip {{ background: {c['card_hi']}; color: {c['text']}; border: 1px solid {c['border_hi']}; padding: 7px 9px; border-radius: 7px; }}

/* sidebar */
QFrame#sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['border']}; }}
QLabel#brand {{ font-size: {pt(13.5)}; font-weight: 700; letter-spacing: 0.3px; }}
QLabel#brandSub {{ color: {c['muted']}; font-size: {pt(8.5)}; }}
QPushButton#nav {{
    text-align: left; padding: 10px 14px; border: none; border-radius: 10px;
    background: transparent; color: {c['muted']}; font-weight: 600;
}}
QPushButton#nav:hover {{ background: {c['card']}; color: {c['text']}; }}
QPushButton#nav:checked {{ background: {sel}; color: {c['text']}; }}

/* page */
QLabel#pageTitle {{ font-size: {pt(19)}; font-weight: 700; }}
QLabel#pageSub {{ color: {c['muted']}; font-size: {pt(10)}; }}
QLabel#cardTitle {{ font-size: {pt(11)}; font-weight: 700; }}
QLabel#muted {{ color: {c['muted']}; }}
QLabel#faint {{ color: {c['faint']}; font-size: {pt(9)}; }}
QLabel#tileValue {{ font-size: {pt(18)}; font-weight: 700; }}
QLabel#tileLabel {{ color: {c['muted']}; font-size: {pt(8.5)}; font-weight: 700; letter-spacing: 0.8px; }}
QLabel#heroTitle {{ font-size: {pt(20)}; font-weight: 800; color: #FFFFFF; background: transparent; }}
QLabel#heroSub {{ font-size: {pt(10.5)}; color: #DCE6F5; background: transparent; }}
QLabel#heroChip {{ background: rgba(0, 0, 0, 0.35); color: #FFFFFF; border: 1px solid rgba(255,255,255,0.25);
                   border-radius: 10px; padding: 4px 10px; font-weight: 600; font-size: {pt(9)}; }}
QLabel#badgeExp {{ background: {rgba(c['warning'], 0.16)}; color: {c['warning']}; border-radius: 6px;
                   padding: 1px 7px; font-size: {pt(7.5)}; font-weight: 700; }}
QLabel#banner {{ background: {rgba(c['accent'], 0.10)}; border: 1px solid {rgba(c['accent'], 0.40)};
                 border-radius: 10px; padding: 10px 13px; }}
QLabel#bannerWarn {{ background: {rgba(c['warning'], 0.10)}; border: 1px solid {rgba(c['warning'], 0.45)};
                     border-radius: 10px; padding: 10px 13px; }}
QLabel#bannerError {{ background: {rgba(c['danger'], 0.10)}; border: 1px solid {rgba(c['danger'], 0.50)};
                      border-radius: 10px; padding: 10px 13px; }}
QFrame#card {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QFrame#tile {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 13px; }}
QFrame#themeCard {{ background: {c['surface']}; border: 2px solid {c['border']}; border-radius: 13px; }}
QFrame#themeCard[selected="true"] {{ border: 2px solid {c['primary']}; }}
QFrame#hline {{ background: {c['border']}; max-height: 1px; min-height: 1px; }}
QFrame#toast {{ background: {c['card_hi']}; border: 1px solid {c['border_hi']}; border-radius: 12px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

/* buttons */
QPushButton {{
    background: {c['card_hi']}; border: 1px solid {c['border_hi']}; border-radius: 10px;
    padding: 8px 15px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {c['primary']}; }}
QPushButton:pressed {{ background: {c['border']}; }}
QPushButton:disabled {{ color: {c['faint']}; border-color: {c['border']}; background: {c['surface']}; }}
QPushButton:focus {{ outline: none; border-color: {c['primary_hi']}; }}
QPushButton:checked {{ border-color: {c['primary']}; background: {sel}; }}
QPushButton#nav:checked {{ border: none; }}
QPushButton#primary {{ background: {c['primary']}; border: 1px solid {c['primary']}; color: {c['on_primary']}; }}
QPushButton#primary:hover {{ background: {c['primary_hi']}; border-color: {c['primary_hi']}; }}
QPushButton#primary:disabled {{ background: {c['card_hi']}; color: {c['faint']}; border-color: {c['border']}; }}
QPushButton#danger {{ background: {rgba(c['danger'], 0.14)}; border: 1px solid {c['danger']}; color: {c['danger_hi']}; }}
QPushButton#danger:hover {{ background: {c['danger']}; color: white; }}
QFrame#hero QPushButton {{ background: {c['card_hi']}; }}
QFrame#hero QPushButton#primary {{ background: {c['primary']}; }}
QFrame#hero QPushButton#primary:disabled {{ background: {c['card_hi']}; }}
QFrame#hero QPushButton#danger {{ background: {c['card']}; }}
QFrame#hero QPushButton#danger:hover {{ background: {c['danger']}; }}
QPushButton[class="big"] {{ padding: 12px 22px; font-size: {pt(11)}; border-radius: 12px; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {c['muted']}; }}
QPushButton#ghost:hover {{ color: {c['text']}; border-color: {c['border_hi']}; }}

/* inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 6px 9px;
    selection-background-color: {c['primary']}; selection-color: {c['on_primary']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {c['primary']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['card_hi']}; border: 1px solid {c['border_hi']};
                               selection-background-color: {c['primary']}; selection-color: {c['on_primary']}; }}
QCheckBox {{ spacing: 9px; }}
QCheckBox::indicator {{ width: 36px; height: 19px; border-radius: 9px; background: {c['border_hi']}; }}
QCheckBox::indicator:checked {{ background: {c['primary']}; }}
QCheckBox::indicator:disabled {{ background: {c['border']}; }}

/* lists / tables / tabs */
QListWidget, QTableWidget, QTreeWidget {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 11px; outline: none;
    alternate-background-color: {c['card']};
}}
QListWidget::item {{ padding: 7px 9px; border-radius: 7px; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background: {rgba(c['primary'], 0.28)}; color: {c['text']}; }}
QHeaderView::section {{ background: {c['card']}; color: {c['muted']}; border: none; border-bottom: 1px solid {c['border']};
                        padding: 7px; font-weight: 600; }}
QTableWidget {{ gridline-color: {c['border']}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 9px 15px; margin-right: 4px;
                border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['primary']}; }}
QTabBar::tab:hover {{ color: {c['text']}; }}
QProgressBar {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 7px; height: 12px;
                text-align: center; font-size: {pt(8)}; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c['primary']}, stop:1 {c['accent']}); border-radius: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border_hi']}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border_hi']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ background: {c['sidebar']}; border-top: 1px solid {c['border']}; color: {c['muted']}; }}
QStatusBar QLabel {{ color: {c['muted']}; padding: 0 9px; }}
QMenu {{ background: {c['card_hi']}; border: 1px solid {c['border_hi']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['primary']}; color: {c['on_primary']}; }}
QMessageBox, QDialog {{ background: {c['card']}; }}
"""
