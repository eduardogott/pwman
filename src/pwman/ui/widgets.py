"""Reusable widgets: password field, strength meter, 2FA countdown, toast, etc."""

from __future__ import annotations

import html

from PySide6.QtCore import QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from ..core import strength
from . import icons, platform, theme


def fit_height(widget: QWidget) -> None:
    """Grow a window so word-wrapped labels are never squeezed."""
    lay = widget.layout()
    if lay is None:
        return
    need = (lay.totalHeightForWidth(widget.width()) if lay.hasHeightForWidth()
            else lay.sizeHint().height())
    if need > widget.height():
        widget.resize(widget.width(), need)


class Dialog(QDialog):
    """QDialog that sizes itself to fit wrapped text when shown."""

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        fit_height(self)

    def refit(self) -> None:
        QTimer.singleShot(0, lambda: fit_height(self))


def button(text: str, *, primary=False, danger=False, link=False, icon_name: str | None = None,
           tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    if primary:
        btn.setProperty("primary", True)
    if danger:
        btn.setProperty("danger", True)
    if link:
        btn.setProperty("link", True)
        btn.setCursor(Qt.PointingHandCursor)
    if icon_name:
        btn.setIcon(icons.icon(icon_name, "#ffffff" if primary else "#8a91a3"))
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def tool_button(icon_name: str, tooltip: str, checkable=False) -> QToolButton:
    btn = QToolButton()
    btn.setIcon(icons.icon(icon_name))
    btn.setIconSize(QSize(18, 18))
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setCheckable(checkable)
    btn.setAutoRaise(True)
    return btn


def label(text: str = "", *, muted=False, heading=False, subheading=False, error=False,
          warning=False, field=False, wrap=False, selectable=False) -> QLabel:
    lbl = QLabel(text)
    for name, on in (("muted", muted), ("heading", heading), ("subheading", subheading),
                     ("error", error), ("warning", warning), ("fieldLabel", field)):
        if on:
            lbl.setProperty(name, True)
    if wrap:
        lbl.setWordWrap(True)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lbl


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    return line


def set_invalid(widget: QWidget, invalid: bool) -> None:
    widget.setProperty("invalid", invalid)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def colorize_password(password: str) -> str:
    """HTML with digits and symbols coloured, to make similar characters easier to read."""
    c = theme.colors()
    out = []
    for ch in password:
        esc = html.escape(ch)
        if ch == " ":
            esc = "&nbsp;"
        if ch.isdigit():
            out.append(f'<span style="color:{c["accent"]}">{esc}</span>')
        elif not ch.isalnum():
            out.append(f'<span style="color:#e8590c">{esc}</span>')
        else:
            out.append(esc)
    return "".join(out)


class PasswordEdit(QLineEdit):
    """Password input with a show/hide toggle and a Caps Lock warning (Windows)."""

    caps_lock_changed = Signal(bool)

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setEchoMode(QLineEdit.Password)
        self.setPlaceholderText(placeholder)
        self.setFont(theme.monospace_font())
        self._toggle = self.addAction(icons.icon("eye"), QLineEdit.TrailingPosition)
        self._toggle.setToolTip("Show / hide")
        self._toggle.triggered.connect(self.toggle_visible)
        self._caps = False

    def toggle_visible(self) -> None:
        self.set_visible(self.echoMode() == QLineEdit.Password)

    def set_visible(self, visible: bool) -> None:
        self.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self._toggle.setIcon(icons.icon("eye-off" if visible else "eye"))

    def _check_caps(self) -> None:
        caps = platform.caps_lock_on()
        if caps != self._caps:
            self._caps = caps
            self.caps_lock_changed.emit(caps)

    def keyPressEvent(self, event):  # noqa: N802
        super().keyPressEvent(event)
        self._check_caps()

    def focusInEvent(self, event):  # noqa: N802
        super().focusInEvent(event)
        self._check_caps()


class StrengthMeter(QWidget):
    """Coloured bar + label for a :class:`StrengthReport`."""

    def __init__(self, parent=None, show_text=True):
        super().__init__(parent)
        self._score = 0
        self._label = "Empty"
        self._show_text = show_text
        self.setMinimumHeight(22 if show_text else 8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_report(self, report: strength.StrengthReport | None) -> None:
        if report is None:
            self._score, self._label = 0, "Empty"
        else:
            self._score, self._label = report.score, report.label
        self.update()

    def sizeHint(self):  # noqa: N802
        return QSize(200, 22 if self._show_text else 8)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = theme.colors()
        bar_h = 6
        text_w = 150 if self._show_text else 0
        bar = QRectF(0, (self.height() - bar_h) / 2, max(10, self.width() - text_w), bar_h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["border"]))
        p.drawRoundedRect(bar, 3, 3)
        if self._score > 0:
            filled = QRectF(bar.x(), bar.y(), bar.width() * max(4, self._score) / 100, bar_h)
            p.setBrush(QColor(theme.strength_color(self._label)))
            p.drawRoundedRect(filled, 3, 3)
        if self._show_text:
            p.setPen(QColor(theme.strength_color(self._label)))
            f = QFont(self.font())
            f.setBold(True)
            p.setFont(f)
            text = self._label if self._label == "Empty" else f"{self._label}  {self._score}/100"
            p.drawText(QRectF(bar.right() + 12, 0, text_w - 12, self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()


class ScoreBreakdown(QWidget):
    """Sub-score rows: strength, length, variety, age."""

    ROWS = [("strength", "Guessability", "How hard it is to guess (dictionary words, patterns, "
                                         "common passwords)"),
            ("length", "Length", "Number of characters - 16+ is ideal"),
            ("variety", "Variety", "Mix of lower/upper case, numbers and symbols"),
            ("age", "Age", "Days since the password was last changed")]

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self._bars: dict[str, QProgressBar] = {}
        self._values: dict[str, QLabel] = {}
        for row, (key, name, tip) in enumerate(self.ROWS):
            name_lbl = label(name, muted=True)
            name_lbl.setToolTip(tip)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            value = label("", muted=True)
            value.setMinimumWidth(110)
            grid.addWidget(name_lbl, row, 0)
            grid.addWidget(bar, row, 1)
            grid.addWidget(value, row, 2)
            self._bars[key], self._values[key] = bar, value
        grid.setColumnStretch(1, 1)

    def _set(self, key: str, score: int | None, text: str) -> None:
        bar = self._bars[key]
        bar.setValue(score or 0)
        label_for = strength.label_for(score or 0)
        c = theme.colors()
        bar.setStyleSheet(
            f"QProgressBar {{ background: {c['border']}; border: none; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: {theme.strength_color(label_for)}; border-radius: 2px; }}"
        )
        self._values[key].setText(text)

    def set_report(self, report: strength.StrengthReport, password: str) -> None:
        self._set("strength", report.strength_score, f"{report.strength_score}/100")
        self._set("length", report.length_score, f"{len(password)} characters")
        classes = sum(strength.character_classes(password).values())
        self._set("variety", report.variety_score, f"{classes} of 4 character types")
        if report.age_score is None:
            self._set("age", 0, "unknown")
        else:
            days = report.age_days or 0
            self._set("age", report.age_score, "today" if days == 0 else f"{days} day{'s' * (days != 1)}")


class TotpRing(QWidget):
    """Circular countdown showing seconds until the 2FA code changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._remaining = 30.0
        self._period = 30
        self.setFixedSize(34, 34)

    def set_time(self, remaining: float, period: int) -> None:
        self._remaining, self._period = remaining, period
        self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = theme.colors()
        rect = QRectF(3, 3, self.width() - 6, self.height() - 6)
        p.setPen(QPen(QColor(c["border"]), 3))
        p.drawEllipse(rect)
        frac = max(0.0, min(1.0, self._remaining / self._period))
        color = QColor(c["danger"] if self._remaining <= 5 else c["accent"])
        p.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 90 * 16, int(-360 * 16 * frac))
        p.setPen(QColor(c["text"]))
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        p.drawText(rect, Qt.AlignCenter, str(int(self._remaining) + (0 if self._remaining == int(self._remaining) else 1)))
        p.end()


class Avatar(QWidget):
    """Coloured circle with the first letter of the entry title."""

    def __init__(self, size=36, parent=None):
        super().__init__(parent)
        self._text = "?"
        self.setFixedSize(size, size)

    def set_text(self, text: str) -> None:
        self._text = text or "?"
        self.update()

    def paintEvent(self, _):  # noqa: N802
        paint_avatar(QPainter(self), QRectF(0, 0, self.width(), self.height()), self._text, end=True)


def paint_avatar(p: QPainter, rect: QRectF, text: str, end=False) -> None:
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.avatar_color(text)))
    p.drawRoundedRect(rect, rect.width() * 0.28, rect.width() * 0.28)
    p.setPen(QColor("#ffffff"))
    f = QFont(p.font())
    f.setBold(True)
    f.setPixelSize(int(rect.height() * 0.45))
    p.setFont(f)
    letter = next((ch for ch in text if ch.isalnum()), "?").upper()
    p.drawText(rect, Qt.AlignCenter, letter)
    if end:
        p.end()


class Toast(QLabel):
    """Short-lived notification shown at the bottom of a window."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.hide()
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.finished.connect(self._on_anim_done)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

    def show_message(self, text: str, msec: int = 2600) -> None:
        c = theme.colors()
        self.setStyleSheet(
            f"background: {c['text']}; color: {c['bg']}; border-radius: 8px; padding: 9px 16px;"
        )
        self.setText(text)
        parent = self.parentWidget()
        width = min(self.fontMetrics().horizontalAdvance(text) + 48, parent.width() - 40)
        self.setFixedWidth(max(160, width))
        self.setFixedHeight(self.heightForWidth(self.width()))
        self.move((parent.width() - width) // 2, parent.height() - self.height() - 36)
        self.raise_()
        self._anim.stop()
        self._effect.setOpacity(1.0)
        self.show()
        self._timer.start(msec)

    def _fade_out(self) -> None:
        self._anim.setDuration(350)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_done(self) -> None:
        if self._effect.opacity() == 0.0:
            self.hide()


class Card(QFrame):
    def __init__(self, parent=None, margins=(16, 14, 16, 14), spacing=8):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(spacing)


def hbox(*widgets, spacing=8, margins=(0, 0, 0, 0), stretch_at: int | None = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for i, w in enumerate(widgets):
        if i == stretch_at:
            lay.addStretch(1)
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay
