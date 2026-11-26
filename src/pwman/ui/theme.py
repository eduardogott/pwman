"""Light/dark colour themes, applied via QPalette + a Qt style sheet."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#f5f6fa", "surface": "#ffffff", "surface_alt": "#eef0f5", "border": "#dde1ea",
    "text": "#1c2230", "muted": "#687084", "accent": "#4f46e5", "accent_hover": "#4338ca",
    "accent_text": "#ffffff", "danger": "#d92d20", "selection": "#e6e5fc", "hover": "#f2f3f8",
    "warning_bg": "#fff7e0", "warning_text": "#7a5300",
}
DARK = {
    "bg": "#14161b", "surface": "#1c1f26", "surface_alt": "#232731", "border": "#323744",
    "text": "#e6e8ee", "muted": "#9aa1b3", "accent": "#7b73ff", "accent_hover": "#8f88ff",
    "accent_text": "#ffffff", "danger": "#ff6b61", "selection": "#2e2b57", "hover": "#252a35",
    "warning_bg": "#3a2f12", "warning_text": "#f3d58a",
}

STRENGTH_COLORS = {
    "Empty": "#9aa1b3", "Very weak": "#e5484d", "Weak": "#f2733a", "Fair": "#e0a800",
    "Good": "#5bb85d", "Strong": "#2f9e66",
}

AVATAR_COLORS = ["#4f46e5", "#0891b2", "#059669", "#d97706", "#dc2626", "#7c3aed",
                 "#db2777", "#2563eb", "#65a30d", "#ea580c"]

_current = dict(LIGHT)


def colors() -> dict[str, str]:
    return _current


def is_dark() -> bool:
    return _current is DARK or _current == DARK


def strength_color(label: str) -> str:
    return STRENGTH_COLORS.get(label, STRENGTH_COLORS["Empty"])


def avatar_color(text: str) -> str:
    return AVATAR_COLORS[sum(ord(c) for c in (text or "?")) % len(AVATAR_COLORS)]


def system_prefers_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return QApplication.palette().color(QPalette.Window).lightness() < 128


def monospace_font(point_size: float | None = None) -> QFont:
    font = QFont()
    font.setFamilies(["Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "Menlo",
                      "monospace"])
    font.setStyleHint(QFont.StyleHint.Monospace)
    if point_size:
        font.setPointSizeF(point_size)
    return font


def apply(app: QApplication, mode: str = "system") -> None:
    global _current
    dark = system_prefers_dark() if mode == "system" else mode == "dark"
    _current = DARK if dark else LIGHT
    c = _current
    app.setStyle("Fusion")

    pal = QPalette()
    roles = {
        QPalette.Window: c["bg"], QPalette.WindowText: c["text"], QPalette.Base: c["surface"],
        QPalette.AlternateBase: c["surface_alt"], QPalette.Text: c["text"],
        QPalette.Button: c["surface"], QPalette.ButtonText: c["text"],
        QPalette.Highlight: c["accent"], QPalette.HighlightedText: c["accent_text"],
        QPalette.ToolTipBase: c["surface"], QPalette.ToolTipText: c["text"],
        QPalette.PlaceholderText: c["muted"], QPalette.Link: c["accent"],
        QPalette.Mid: c["border"], QPalette.Midlight: c["surface_alt"], QPalette.Dark: c["border"],
        QPalette.Light: c["surface"], QPalette.Shadow: "#000000", QPalette.BrightText: c["danger"],
    }
    for role, value in roles.items():
        pal.setColor(role, QColor(value))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(c["muted"]))
    app.setPalette(pal)

    font = app.font()
    if font.pointSizeF() < 10:
        font.setPointSizeF(10)
        app.setFont(font)
    up, down = _arrow_files(c["muted"])
    app.setStyleSheet(STYLE_SHEET.format(**c, arrow_up=up, arrow_down=down))


def _arrow_files(color: str) -> tuple[str, str]:
    """Style sheets can only load arrow images from files, so write two tiny SVGs."""
    folder = Path(tempfile.gettempdir()) / "pwman-ui"
    paths = []
    for name, points in (("up", "3,10 8,5 13,10"), ("down", "3,6 8,11 13,6")):
        path = folder / f"chevron-{name}-{color.lstrip('#')}.svg"
        if not path.exists():
            try:
                folder.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">'
                    f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.8" '
                    f'stroke-linecap="round" stroke-linejoin="round"/></svg>', "utf-8")
            except OSError:
                pass
        paths.append(path.as_posix())
    return paths[0], paths[1]


STYLE_SHEET = """
QMainWindow, QDialog {{ background: {bg}; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 4px 6px; }}
QLabel[muted="true"] {{ color: {muted}; }}
QLabel[heading="true"] {{ font-size: 15pt; font-weight: 600; }}
QLabel[subheading="true"] {{ font-size: 11pt; font-weight: 600; }}
QLabel[error="true"] {{ color: {danger}; }}
QLabel[warning="true"] {{ background: {warning_bg}; color: {warning_text}; border-radius: 6px; padding: 8px 10px; }}
QLabel[fieldLabel="true"] {{ color: {muted}; font-size: 9pt; }}

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {accent}; selection-color: {accent_text};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {accent}; }}
QLineEdit:read-only {{ background: {surface_alt}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {danger}; }}
QSpinBox {{ padding-right: 24px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; width: 20px; border: none; background: transparent; margin-right: 3px;
}}
QSpinBox::up-button {{ subcontrol-position: top right; margin-top: 3px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 3px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {hover}; border-radius: 4px; }}
QSpinBox::up-arrow {{ image: url("{arrow_up}"); width: 11px; height: 11px; }}
QSpinBox::down-arrow {{ image: url("{arrow_down}"); width: 11px; height: 11px; }}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{ image: none; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }}
QComboBox::down-arrow {{ image: url("{arrow_down}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {surface}; border: 1px solid {border}; padding: 4px; outline: none;
    selection-background-color: {selection}; selection-color: {text};
}}

QPushButton {{
    background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 6px 14px;
    min-height: 20px;
}}
QPushButton:hover {{ background: {hover}; }}
QPushButton:pressed {{ background: {surface_alt}; }}
QPushButton:disabled {{ color: {muted}; }}
QPushButton:checked {{ background: {selection}; border-color: {accent}; font-weight: 600; }}
QPushButton[primary="true"] {{ background: {accent}; color: {accent_text}; border: 1px solid {accent}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {accent_hover}; }}
QPushButton[primary="true"]:disabled {{ background: {border}; border-color: {border}; color: {muted}; }}
QPushButton[danger="true"] {{ color: {danger}; }}
QPushButton[link="true"] {{ background: transparent; border: none; color: {accent}; padding: 2px 4px; text-align: left; }}
QPushButton[link="true"]:hover {{ text-decoration: underline; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px; }}
QToolButton:hover {{ background: {hover}; border-color: {border}; }}
QToolButton:checked {{ background: {selection}; }}

QListView, QListWidget, QTableWidget, QTreeWidget {{
    background: {surface}; border: 1px solid {border}; border-radius: 8px; outline: none;
}}
QListWidget#Sidebar {{ background: transparent; border: none; }}
QListWidget#Sidebar::item {{ padding: 7px 10px; border-radius: 6px; margin: 1px 4px; }}
QListWidget#Sidebar::item:selected {{ background: {selection}; color: {text}; }}
QListWidget#Sidebar::item:hover:!selected {{ background: {hover}; }}
QTableWidget::item:selected {{ background: {selection}; color: {text}; }}
QHeaderView::section {{ background: {surface_alt}; border: none; border-bottom: 1px solid {border}; padding: 5px 8px; }}

QFrame#Card {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
QFrame#DetailPane, QScrollArea#DetailScroll {{ background: transparent; border: none; }}
QWidget#DetailContent {{ background: transparent; }}
QFrame#Divider {{ background: {border}; max-height: 1px; min-height: 1px; border: none; }}

QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; top: -1px; background: {surface}; }}
QTabBar::tab {{ background: transparent; padding: 7px 14px; border: none; color: {muted}; }}
QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {accent}; font-weight: 600; }}

QCheckBox {{ spacing: 8px; }}
QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {accent}; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }}
QMenuBar {{ background: {bg}; }}
QMenuBar::item:selected {{ background: {hover}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {selection}; color: {text}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 6px; }}
QStatusBar {{ color: {muted}; }}
QSplitter::handle {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; margin: 2px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""
