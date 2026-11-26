"""The unlocked vault: sidebar filters, entry list and entry details."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QListView, QListWidget, QListWidgetItem, QScrollArea,
    QSplitter, QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from ..core import analysis, totp
from ..core.csv_io import _title_from_url
from ..core.models import Entry, age_in_days
from ..core.strength import StrengthReport
from . import icons, theme
from .dialogs import fmt_date
from .widgets import (
    Avatar, Card, ScoreBreakdown, StrengthMeter, TotpRing, button, colorize_password, divider,
    label, paint_avatar, tool_button,
)

ENTRY_ROLE = Qt.UserRole
REPORT_ROLE = Qt.UserRole + 1

FILTERS = [
    ("all", "All items", "list"),
    ("favorites", "Favorites", "star"),
    ("totp", "With 2FA", "shield"),
    (None, "Password health", None),
    ("weak", "Weak", "alert"),
    ("reused", "Reused", "repeat"),
    ("old", "Old", "clock"),
]


# --------------------------------------------------------------------------- list model / delegate


class EntryListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[Entry] = []
        self.reports: dict[str, StrengthReport] = {}

    def set_items(self, items: list[Entry], reports: dict[str, StrengthReport]) -> None:
        self.beginResetModel()
        self.items = items
        self.reports = reports
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return None
        entry = self.items[index.row()]
        if role == Qt.DisplayRole:
            return entry.title
        if role == ENTRY_ROLE:
            return entry
        if role == REPORT_ROLE:
            return self.reports.get(entry.id)
        return None

    def row_of(self, entry_id: str) -> int:
        return next((i for i, e in enumerate(self.items) if e.id == entry_id), -1)


class EntryDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):  # noqa: N802
        return QSize(200, 58)

    def paint(self, p: QPainter, option, index):
        entry: Entry = index.data(ENTRY_ROLE)
        report: StrengthReport | None = index.data(REPORT_ROLE)
        if entry is None:
            return
        c = theme.colors()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(4, 2, -4, -2)
        if option.state & QStyle.State_Selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["selection"]))
            p.drawRoundedRect(r, 8, 8)
        elif option.state & QStyle.State_MouseOver:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["hover"]))
            p.drawRoundedRect(r, 8, 8)

        av = QRectF(r.left() + 10, r.center().y() - 17, 34, 34)
        paint_avatar(p, av, entry.title)

        badges_w = 64
        text_x = av.right() + 12
        text_w = r.right() - text_x - badges_w
        title_font = QFont(option.font)
        title_font.setWeight(QFont.DemiBold)
        p.setFont(title_font)
        p.setPen(QColor(c["text"]))
        fm = QFontMetrics(title_font)
        p.drawText(QRectF(text_x, r.top() + 9, text_w, fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(entry.title, Qt.ElideRight, int(text_w)))
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(max(7.5, option.font.pointSizeF() - 1))
        p.setFont(sub_font)
        p.setPen(QColor(c["muted"]))
        fm2 = QFontMetrics(sub_font)
        subtitle = entry.username or _title_from_url(entry.url) or " "
        p.drawText(QRectF(text_x, r.bottom() - 9 - fm2.height(), text_w, fm2.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, fm2.elidedText(subtitle, Qt.ElideRight, int(text_w)))

        # badges, right to left: strength dot, 2FA, favourite star
        x = r.right() - 14
        cy = r.center().y()
        if report is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.strength_color(report.label)))
            p.drawEllipse(QRectF(x - 8, cy - 4, 8, 8))
        x -= 16
        if entry.totp:
            f = QFont(option.font)
            f.setPointSizeF(7)
            f.setBold(True)
            p.setFont(f)
            pill = QRectF(x - 26, cy - 8, 26, 16)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["surface_alt"]))
            p.drawRoundedRect(pill, 5, 5)
            p.setPen(QColor(c["muted"]))
            p.drawText(pill, Qt.AlignCenter, "2FA")
            x -= 32
        if entry.favorite:
            icons.icon("star-filled", "#f5b400").paint(p, int(x - 14), int(cy - 7), 14, 14)
        p.restore()


# --------------------------------------------------------------------------- detail pane


class FieldRow(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(6)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(title.upper(), field=True))
        self.value = label("", selectable=True)
        self.value.setTextFormat(Qt.PlainText)
        col.addWidget(self.value)
        lay.addLayout(col, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(2)
        lay.addLayout(self.buttons)

    def add_button(self, btn) -> None:
        self.buttons.addWidget(btn)


class EntryDetail(QWidget):
    copy_requested = Signal(str, str)  # value, what
    edit_requested = Signal()
    delete_requested = Signal()
    favorite_toggled = Signal(bool)
    open_url_requested = Signal(str)
    history_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entry: Entry | None = None
        self._revealed = False
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # header
        head = QHBoxLayout()
        self.avatar = Avatar(48)
        head.addWidget(self.avatar)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        self.title = label("", heading=True, selectable=True)
        self.title.setTextFormat(Qt.PlainText)
        self.subtitle = label("", muted=True)
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        head.addLayout(title_box, 1)
        self.fav_btn = tool_button("star", "Favorite", checkable=True)
        self.fav_btn.toggled.connect(self._fav_toggled)
        edit = button("Edit", icon_name="edit")
        delete = tool_button("trash", "Delete entry")
        edit.clicked.connect(self.edit_requested.emit)
        delete.clicked.connect(self.delete_requested.emit)
        head.addWidget(self.fav_btn)
        head.addWidget(edit)
        head.addWidget(delete)
        root.addLayout(head)

        # credentials card
        card = Card(spacing=6)
        self.username_row = FieldRow("Username")
        self.username_row.add_button(self._copy_btn(lambda: (self.entry.username, "Username")))
        self.password_row = FieldRow("Password")
        self.password_row.value.setFont(theme.monospace_font(11))
        self.password_row.value.setTextFormat(Qt.RichText)
        self.reveal_btn = tool_button("eye", "Show password")
        self.reveal_btn.clicked.connect(self._toggle_reveal)
        self.password_row.add_button(self.reveal_btn)
        self.password_row.add_button(self._copy_btn(lambda: (self.entry.password, "Password")))
        self.totp_row = FieldRow("2FA code")
        self.totp_row.value.setFont(theme.monospace_font(16))
        self.totp_ring = TotpRing()
        self.totp_row.add_button(self.totp_ring)
        self.totp_row.add_button(self._copy_btn(lambda: (totp.generate(self.entry.totp), "2FA code")))
        self.url_row = FieldRow("Website")
        open_btn = tool_button("external", "Open in browser")
        open_btn.clicked.connect(lambda: self.open_url_requested.emit(self.entry.url))
        self.url_row.add_button(open_btn)
        self.url_row.add_button(self._copy_btn(lambda: (self.entry.url, "Website address"), secret=False))
        self._rows = [self.username_row, self.password_row, self.totp_row, self.url_row]
        self._dividers = []
        for i, row in enumerate(self._rows):
            if i:
                d = divider()
                self._dividers.append(d)
                card.body.addWidget(d)
            card.body.addWidget(row)
        root.addWidget(card)

        # health card
        self.health = Card(spacing=8)
        h_head = QHBoxLayout()
        h_head.addWidget(label("Password health", subheading=True))
        h_head.addStretch(1)
        self.history_btn = button("History", link=True)
        self.history_btn.clicked.connect(self.history_requested.emit)
        h_head.addWidget(self.history_btn)
        self.health.body.addLayout(h_head)
        self.meter = StrengthMeter()
        self.health.body.addWidget(self.meter)
        self.breakdown = ScoreBreakdown()
        self.health.body.addWidget(self.breakdown)
        self.crack = label("", muted=True, wrap=True)
        self.health.body.addWidget(self.crack)
        self.feedback = label("", wrap=True)
        self.health.body.addWidget(self.feedback)
        root.addWidget(self.health)

        # notes
        self.notes_card = Card(spacing=4)
        self.notes_card.body.addWidget(label("NOTES", field=True))
        self.notes = label("", wrap=True, selectable=True)
        self.notes.setTextFormat(Qt.PlainText)
        self.notes_card.body.addWidget(self.notes)
        root.addWidget(self.notes_card)

        self.dates = label("", muted=True, wrap=True)
        root.addWidget(self.dates)
        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)

    def _copy_btn(self, getter, secret=True):
        btn = tool_button("copy", "Copy")
        btn.clicked.connect(lambda: self.copy_requested.emit(*getter()) if self.entry else None)
        btn.setProperty("secret", secret)
        return btn

    def _fav_toggled(self, on: bool) -> None:
        self.fav_btn.setIcon(icons.icon("star-filled", "#f5b400") if on else icons.icon("star"))
        if self.entry is not None and on != self.entry.favorite:
            self.favorite_toggled.emit(on)

    def _toggle_reveal(self) -> None:
        self._revealed = not self._revealed
        self._show_password()

    def _show_password(self) -> None:
        pw = self.entry.password if self.entry else ""
        if self._revealed:
            self.password_row.value.setText(colorize_password(pw))
        else:
            self.password_row.value.setText("•" * min(16, max(8, len(pw))))
        self.reveal_btn.setIcon(icons.icon("eye-off" if self._revealed else "eye"))
        self.reveal_btn.setToolTip("Hide password" if self._revealed else "Show password")

    def set_entry(self, entry: Entry, report: StrengthReport | None) -> None:
        same = self.entry is not None and self.entry.id == entry.id
        self.entry = entry
        if not same:
            self._revealed = False
        self.avatar.set_text(entry.title)
        self.title.setText(entry.title)
        self.subtitle.setText(_title_from_url(entry.url))
        self.subtitle.setVisible(bool(entry.url))
        self.fav_btn.blockSignals(True)
        self.fav_btn.setChecked(entry.favorite)
        self.fav_btn.blockSignals(False)
        self.fav_btn.setIcon(icons.icon("star-filled", "#f5b400") if entry.favorite else icons.icon("star"))

        self.username_row.value.setText(entry.username)
        self.username_row.setVisible(bool(entry.username))
        self.password_row.setVisible(bool(entry.password))
        self._show_password()
        self.totp_row.setVisible(entry.totp is not None)
        self.url_row.value.setText(entry.url)
        self.url_row.setVisible(bool(entry.url))
        for i, d in enumerate(self._dividers):
            above = any(not r.isHidden() for r in self._rows[: i + 1])
            d.setVisible(above and not self._rows[i + 1].isHidden())

        if entry.totp:
            self._tick()
            self._timer.start()
        else:
            self._timer.stop()

        self.health.setVisible(bool(entry.password) and report is not None)
        if entry.password and report is not None:
            self.meter.set_report(report)
            self.breakdown.set_report(report, entry.password)
            self.crack.setText(f"Estimated time to crack offline: {report.crack_time}."
                               if report.crack_time else "")
            self.feedback.setText("\n".join(f"• {f}" for f in report.feedback)
                                  if report.feedback else "✔ No problems found.")
        n = len(entry.password_history)
        self.history_btn.setText(f"History ({n})")
        self.history_btn.setVisible(n > 0)

        self.notes.setText(entry.notes)
        self.notes_card.setVisible(bool(entry.notes.strip()))
        changed = age_in_days(entry.password_changed_at)
        changed_txt = ("today" if changed == 0 else f"{changed} days ago") if changed is not None else "-"
        self.dates.setText(f"Created {fmt_date(entry.created_at)}  ·  Modified "
                           f"{fmt_date(entry.updated_at)}  ·  Password changed {changed_txt}")

    def clear(self) -> None:
        self._timer.stop()
        self.entry = None
        self._revealed = False
        for row in self._rows:
            row.value.clear()
        self.notes.clear()

    def _tick(self) -> None:
        if not self.entry or not self.entry.totp:
            self._timer.stop()
            return
        cfg = self.entry.totp
        try:
            self.totp_row.value.setText(totp.format_code(totp.generate(cfg)))
        except ValueError:
            self.totp_row.value.setText("invalid secret")
        self.totp_ring.set_time(totp.seconds_remaining(cfg), cfg.period)


# --------------------------------------------------------------------------- the page


class VaultView(QWidget):
    new_requested = Signal()
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    copy_requested = Signal(str, str)
    open_url_requested = Signal(str)
    favorite_changed = Signal(str, bool)
    history_requested = Signal(str)
    import_requested = Signal()
    generator_requested = Signal()
    security_requested = Signal()
    settings_requested = Signal()
    lock_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[Entry] = []
        self.reports: dict[str, StrengthReport] = {}
        self.report: analysis.SecurityReport | None = None
        self.max_age_days = 365

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 8)
        root.setSpacing(10)

        # top bar
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, username, website or notes   (Ctrl+F)")
        self.search.addAction(icons.icon("search"), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(34)
        self.search.textChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.search, 1)
        new_btn = button("New entry", primary=True, icon_name="plus")
        new_btn.setMinimumHeight(34)
        new_btn.clicked.connect(self.new_requested.emit)
        bar.addWidget(new_btn)
        for name, tip, sig in (("dice", "Password generator (Ctrl+G)", self.generator_requested),
                               ("shield", "Security report", self.security_requested),
                               ("settings", "Settings", self.settings_requested),
                               ("lock", "Lock vault (Ctrl+L)", self.lock_requested)):
            b = tool_button(name, tip)
            b.setIconSize(QSize(20, 20))
            b.setMinimumSize(34, 34)
            b.clicked.connect(sig.emit)
            bar.addWidget(b)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # sidebar
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setIconSize(QSize(18, 18))
        self.sidebar.setMinimumWidth(170)
        self.sidebar.setMaximumWidth(240)
        self._filter_items: dict[str, QListWidgetItem] = {}
        self._section_items: list[QListWidgetItem] = []
        for key, text, icon_name in FILTERS:
            item = QListWidgetItem(text)
            if key is None:
                item.setFlags(Qt.NoItemFlags)
                f = item.font()
                f.setPointSizeF(8.5)
                f.setBold(True)
                item.setFont(f)
                item.setSizeHint(QSize(100, 34))
                self._section_items.append(item)
            else:
                item.setIcon(icons.icon(icon_name))
                item.setData(Qt.UserRole, key)
                self._filter_items[key] = item
            self.sidebar.addItem(item)
        self.sidebar.setCurrentRow(0)
        self.sidebar.currentItemChanged.connect(lambda *_: self.refresh())
        splitter.addWidget(self.sidebar)

        # entry list
        list_box = QWidget()
        lb = QVBoxLayout(list_box)
        lb.setContentsMargins(0, 0, 0, 0)
        self.model = EntryListModel(self)
        self.list = QListView()
        self.list.setModel(self.model)
        self.list.setItemDelegate(EntryDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setMinimumWidth(260)
        self.list.selectionModel().currentChanged.connect(lambda *_: self._show_current())
        self.list.doubleClicked.connect(lambda _: self._emit_current(self.edit_requested))
        lb.addWidget(self.list)
        splitter.addWidget(list_box)

        # detail / empty states
        self.right = QStackedWidget()
        self.detail = EntryDetail()
        scroll = QScrollArea()
        scroll.setObjectName("DetailScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.detail.setObjectName("DetailContent")
        scroll.setWidget(self.detail)
        self.placeholder = self._make_placeholder()
        self.empty_vault = self._make_empty_vault()
        self.right.addWidget(self.placeholder)
        self.right.addWidget(scroll)
        self.right.addWidget(self.empty_vault)
        self._detail_scroll = scroll
        splitter.addWidget(self.right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([190, 330, 520])
        root.addWidget(splitter, 1)

        self.detail.copy_requested.connect(self.copy_requested.emit)
        self.detail.edit_requested.connect(lambda: self._emit_current(self.edit_requested))
        self.detail.delete_requested.connect(lambda: self._emit_current(self.delete_requested))
        self.detail.open_url_requested.connect(self.open_url_requested.emit)
        self.detail.history_requested.connect(lambda: self._emit_current(self.history_requested))
        self.detail.favorite_toggled.connect(
            lambda on: self.detail.entry and self.favorite_changed.emit(self.detail.entry.id, on))

        copy_pw = QShortcut(QKeySequence.Copy, self.list)
        copy_pw.setContext(Qt.WidgetShortcut)
        copy_pw.activated.connect(self.copy_password)
        enter = QShortcut(QKeySequence(Qt.Key_Return), self.list)
        enter.setContext(Qt.WidgetShortcut)
        enter.activated.connect(lambda: self._emit_current(self.edit_requested))

    def _make_placeholder(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        self.placeholder_text = label("Select an entry to see its details", muted=True)
        lay.addWidget(self.placeholder_text, alignment=Qt.AlignCenter)
        lay.addStretch(2)
        return w

    def _make_empty_vault(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        box = QVBoxLayout()
        box.setSpacing(10)
        box.addWidget(label("Your vault is empty", heading=True), alignment=Qt.AlignCenter)
        box.addWidget(label("Add your first password, or import the passwords saved in your browser\n"
                            "(Chrome, Edge, Firefox) or another password manager.", muted=True),
                      alignment=Qt.AlignCenter)
        row = QHBoxLayout()
        row.addStretch(1)
        add = button("Add a password", primary=True, icon_name="plus")
        imp = button("Import from CSV...", icon_name="import")
        add.clicked.connect(self.new_requested.emit)
        imp.clicked.connect(self.import_requested.emit)
        row.addWidget(add)
        row.addWidget(imp)
        row.addStretch(1)
        box.addLayout(row)
        lay.addLayout(box)
        lay.addStretch(2)
        return w

    # ------------------------------------------------------------------ data
    def set_entries(self, entries: list[Entry], max_age_days: int, select: str | None = None) -> None:
        self.entries = entries
        self.max_age_days = max_age_days
        self.report = analysis.build_report(entries, max_age_days)
        self.reports = self.report.reports
        self._update_counts()
        self.refresh(select)

    def _update_counts(self) -> None:
        for item in self._section_items:
            item.setForeground(QColor(theme.colors()["muted"]))
        r = self.report
        counts = {
            "all": len(self.entries),
            "favorites": sum(e.favorite for e in self.entries),
            "totp": sum(e.totp is not None for e in self.entries),
            "weak": len(r.weak), "reused": len(r.reused), "old": len(r.old),
        }
        for key, text, _ in FILTERS:
            if key:
                n = counts[key]
                self._filter_items[key].setText(f"{text}  ({n})" if n or key == "all" else text)
                if key in ("weak", "reused", "old"):
                    self._filter_items[key].setForeground(
                        QColor(theme.STRENGTH_COLORS["Very weak"] if n else theme.colors()["text"]))

    def current_filter(self) -> str:
        item = self.sidebar.currentItem()
        return item.data(Qt.UserRole) if item else "all"

    def _visible_entries(self) -> list[Entry]:
        f = self.current_filter()
        r = self.report
        if f == "favorites":
            items = [e for e in self.entries if e.favorite]
        elif f == "totp":
            items = [e for e in self.entries if e.totp]
        elif f in ("weak", "reused", "old") and r is not None:
            ids = {e.id for e in getattr(r, f)}
            items = [e for e in self.entries if e.id in ids]
        else:
            items = list(self.entries)
        q = self.search.text().strip().casefold()
        if q:
            items = [e for e in items if any(q in s.casefold() for s in
                                             (e.title, e.username, e.url, e.notes))]
        return sorted(items, key=lambda e: (e.title.casefold(), e.username.casefold()))

    def refresh(self, select: str | None = None) -> None:
        current = select or (self.detail.entry.id if self.detail.entry else None)
        items = self._visible_entries()
        self.model.set_items(items, self.reports)
        row = self.model.row_of(current) if current else -1
        if row < 0 and items:
            row = 0
        if row >= 0:
            self.list.setCurrentIndex(self.model.index(row))
            self.list.scrollTo(self.model.index(row))
        self._show_current()

    def _show_current(self) -> None:
        idx = self.list.currentIndex()
        entry = idx.data(ENTRY_ROLE) if idx.isValid() else None
        if not self.entries:
            self.detail.clear()
            self.right.setCurrentWidget(self.empty_vault)
        elif entry is None:
            self.detail.clear()
            self.placeholder_text.setText("No matching entries" if not self.model.items
                                          else "Select an entry to see its details")
            self.right.setCurrentWidget(self.placeholder)
        else:
            self.detail.set_entry(entry, self.reports.get(entry.id))
            self.right.setCurrentWidget(self._detail_scroll)

    def selected_entry(self) -> Entry | None:
        idx = self.list.currentIndex()
        return idx.data(ENTRY_ROLE) if idx.isValid() else None

    def _emit_current(self, signal) -> None:
        entry = self.selected_entry()
        if entry:
            signal.emit(entry.id)

    def select_entry(self, entry_id: str) -> None:
        self.search.clear()
        self.sidebar.setCurrentRow(0)
        self.refresh(entry_id)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def copy_password(self) -> None:
        e = self.selected_entry()
        if e and e.password:
            self.copy_requested.emit(e.password, "Password")

    def copy_username(self) -> None:
        e = self.selected_entry()
        if e and e.username:
            self.copy_requested.emit(e.username, "Username")

    def copy_totp(self) -> None:
        e = self.selected_entry()
        if e and e.totp:
            self.copy_requested.emit(totp.generate(e.totp), "2FA code")

    def open_url(self) -> None:
        e = self.selected_entry()
        if e and e.url:
            self.open_url_requested.emit(e.url)

    def clear(self) -> None:
        self.detail.clear()
        self.entries = []
        self.reports = {}
        self.report = None
        self.model.set_items([], {})
        self.search.clear()
        self.sidebar.setCurrentRow(0)
