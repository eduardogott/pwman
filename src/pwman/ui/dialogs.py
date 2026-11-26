"""Settings, security report, password history and import dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout,
    QHeaderView, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..core import analysis
from ..core.models import Entry, VaultSettings, parse_iso
from ..core.strength import label_for
from . import platform, theme
from .widgets import Card, Dialog, button, label

THEMES = [("system", "Match Windows"), ("light", "Light"), ("dark", "Dark")]


def fmt_date(iso: str) -> str:
    dt = parse_iso(iso)
    return dt.astimezone().strftime("%d %b %Y, %H:%M") if dt else "-"


class SettingsDialog(Dialog):
    change_password_requested = Signal()
    new_recovery_key_requested = Signal()

    def __init__(self, settings: VaultSettings, theme_mode: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(12)
        lay.addWidget(label("Settings", heading=True))

        sec = Card()
        sec.body.addWidget(label("Security", subheading=True))
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.auto_lock = QSpinBox()
        self.auto_lock.setRange(0, 240)
        self.auto_lock.setSuffix(" min")
        self.auto_lock.setSpecialValueText("Never")
        self.auto_lock.setValue(settings.auto_lock_minutes)
        form.addRow("Lock after inactivity", self.auto_lock)
        self.clip = QSpinBox()
        self.clip.setRange(0, 600)
        self.clip.setSuffix(" s")
        self.clip.setSpecialValueText("Never")
        self.clip.setValue(settings.clipboard_clear_seconds)
        form.addRow("Clear copied passwords after", self.clip)
        self.lock_min = QCheckBox("Lock when the window is minimized")
        self.lock_min.setChecked(settings.lock_on_minimize)
        form.addRow(self.lock_min)
        self.lock_sys = QCheckBox("Lock when the computer is locked (Win+L)")
        self.lock_sys.setChecked(settings.lock_on_system_lock)
        self.lock_sys.setEnabled(platform.IS_WINDOWS)
        form.addRow(self.lock_sys)
        self.capture = QCheckBox("Hide PwMan from screenshots and screen sharing")
        self.capture.setChecked(settings.screen_capture_protection)
        self.capture.setEnabled(platform.IS_WINDOWS)
        form.addRow(self.capture)
        sec.body.addLayout(form)
        lay.addWidget(sec)

        pw = Card()
        pw.body.addWidget(label("Passwords & backups", subheading=True))
        form2 = QFormLayout()
        self.max_age = QSpinBox()
        self.max_age.setRange(0, 3650)
        self.max_age.setSuffix(" days")
        self.max_age.setSpecialValueText("Ignore age")
        self.max_age.setSingleStep(30)
        self.max_age.setValue(settings.password_max_age_days)
        self.max_age.setToolTip("Passwords older than this are flagged as 'old' and score lower.")
        form2.addRow("Recommend changing passwords after", self.max_age)
        self.backups = QSpinBox()
        self.backups.setRange(0, 100)
        self.backups.setSpecialValueText("Off")
        self.backups.setValue(settings.backup_count)
        self.backups.setToolTip("An encrypted copy of the vault is kept each time you unlock and save.")
        form2.addRow("Encrypted backups to keep", self.backups)
        pw.body.addLayout(form2)
        lay.addWidget(pw)

        look = Card()
        look.body.addWidget(label("Appearance", subheading=True))
        form3 = QFormLayout()
        self.theme = QComboBox()
        for key, text in THEMES:
            self.theme.addItem(text, key)
        self.theme.setCurrentIndex(max(0, [k for k, _ in THEMES].index(theme_mode)
                                       if theme_mode in dict(THEMES) else 0))
        form3.addRow("Theme", self.theme)
        look.body.addLayout(form3)
        lay.addWidget(look)

        master = Card()
        master.body.addWidget(label("Master password & recovery key", subheading=True))
        row = QHBoxLayout()
        change = button("Change master password...", icon_name="key")
        newkey = button("Create new recovery key...", icon_name="refresh")
        change.clicked.connect(self.change_password_requested.emit)
        newkey.clicked.connect(self.new_recovery_key_requested.emit)
        row.addWidget(change)
        row.addWidget(newkey)
        row.addStretch(1)
        master.body.addLayout(row)
        lay.addWidget(master)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancel")
        save = button("Save", primary=True)
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(save)
        lay.addLayout(btns)

    def apply_to(self, settings: VaultSettings) -> None:
        settings.auto_lock_minutes = self.auto_lock.value()
        settings.clipboard_clear_seconds = self.clip.value()
        settings.lock_on_minimize = self.lock_min.isChecked()
        settings.lock_on_system_lock = self.lock_sys.isChecked()
        settings.screen_capture_protection = self.capture.isChecked()
        settings.password_max_age_days = self.max_age.value()
        settings.backup_count = self.backups.value()

    def theme_mode(self) -> str:
        return self.theme.currentData()


class SecurityReportDialog(Dialog):
    """Vault-wide password health overview."""

    entry_selected = Signal(str)

    def __init__(self, entries: list[Entry], report: analysis.SecurityReport, max_age_days: int,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Security report")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(12)

        head = QHBoxLayout()
        score_box = QVBoxLayout()
        score_lbl = label(f"{report.overall}")
        color = theme.strength_color(label_for(report.overall))
        score_lbl.setStyleSheet(f"font-size: 34pt; font-weight: 700; color: {color};")
        score_box.addWidget(score_lbl, alignment=Qt.AlignCenter)
        score_box.addWidget(label("vault health", muted=True), alignment=Qt.AlignCenter)
        head.addLayout(score_box)
        head.addSpacing(18)
        text_box = QVBoxLayout()
        text_box.addWidget(label("Security report", heading=True))
        n = len(report.reports)
        if report.issue_count == 0 and n:
            summary = f"All {n} passwords look good. Nice work!"
        elif not n:
            summary = "Add some passwords to see their health here."
        else:
            summary = (f"{report.issue_count} of {n} passwords need attention. Fix the weakest and "
                       "reused ones first - those are the easiest for attackers.")
        text_box.addWidget(label(summary, wrap=True, muted=True))
        head.addLayout(text_box, 1)
        lay.addLayout(head)

        cards = QGridLayout()
        specs = [("Weak", report.weak, "alert"), ("Reused", report.reused, "repeat"),
                 ("Old", report.old, "clock"), ("Without 2FA", report.without_2fa, "shield")]
        for i, (name, items, _) in enumerate(specs):
            card = Card(margins=(14, 10, 14, 10), spacing=2)
            num = label(str(len(items)))
            bad = name != "Without 2FA" and items
            num.setStyleSheet(f"font-size: 18pt; font-weight: 700; color: "
                              f"{theme.STRENGTH_COLORS['Very weak'] if bad else theme.colors()['text']};")
            card.body.addWidget(num)
            card.body.addWidget(label(name, muted=True))
            cards.addWidget(card, 0, i)
        lay.addLayout(cards)

        tabs = QTabWidget()
        by_id = {e.id: e for e in entries}
        tabs.addTab(self._table(report.weak, report, "Rating"), f"Weak ({len(report.weak)})")
        tabs.addTab(self._table(report.reused, report, "Used by", by_id, entries), f"Reused ({len(report.reused)})")
        tabs.addTab(self._table(report.old, report, "Age"), f"Old ({len(report.old)})")
        tabs.addTab(self._table(report.without_2fa, report, "Tip"), f"Without 2FA ({len(report.without_2fa)})")
        lay.addWidget(tabs, 1)
        lay.addWidget(label("Double-click an entry to open it. Passwords older than "
                            f"{max_age_days} days count as old (change this in Settings).",
                            muted=True, wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        close = button("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

    def _table(self, items: list[Entry], report, column: str, by_id=None, entries=None) -> QWidget:
        table = QTableWidget(len(items), 3)
        table.setHorizontalHeaderLabels(["Entry", "Username", column])
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setShowGrid(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for row, e in enumerate(sorted(items, key=lambda x: report.reports.get(x.id).score
                                       if report.reports.get(x.id) else 100)):
            r = report.reports.get(e.id)
            if column == "Rating":
                value = f"{r.label} ({r.quality}/100)" if r else ""
            elif column == "Age":
                value = f"{r.age_days} days" if r and r.age_days is not None else ""
            elif column == "Used by":
                others = [x.title for x in entries if x.id != e.id and x.password == e.password]
                value = ", ".join(others[:3]) + ("..." if len(others) > 3 else "")
            else:
                value = "Enable 2FA on the website if it's offered"
            for col, text in enumerate((e.title, e.username, value)):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, e.id)
                table.setItem(row, col, item)
        table.cellDoubleClicked.connect(
            lambda r, c: self._select(table.item(r, 0).data(Qt.UserRole)))
        return table

    def _select(self, entry_id: str) -> None:
        self.entry_selected.emit(entry_id)
        self.accept()


class HistoryDialog(Dialog):
    def __init__(self, entry: Entry, copy_fn, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Password history - {entry.title}")
        self.resize(560, 360)
        self.entry = entry
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.addWidget(label("Previous passwords", subheading=True))
        lay.addWidget(label(f"Current password set on {fmt_date(entry.password_changed_at)}.", muted=True))
        self.table = QTableWidget(len(entry.password_history), 2)
        self.table.setHorizontalHeaderLabels(["Password", "Replaced on"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.show_check = QCheckBox("Show passwords")
        self.show_check.toggled.connect(self._fill)
        copy = button("Copy selected", icon_name="copy")
        copy.clicked.connect(lambda: self._copy(copy_fn))
        close = button("Close")
        close.clicked.connect(self.accept)
        row.addWidget(self.show_check)
        row.addStretch(1)
        row.addWidget(copy)
        row.addWidget(close)
        lay.addLayout(row)
        self._fill()

    def _fill(self, *_):
        for i, h in enumerate(self.entry.password_history):
            text = h.password if self.show_check.isChecked() else "•" * 10
            item = QTableWidgetItem(text)
            item.setFont(theme.monospace_font())
            self.table.setItem(i, 0, item)
            self.table.setItem(i, 1, QTableWidgetItem(fmt_date(h.changed_at)))

    def _copy(self, copy_fn):
        row = self.table.currentRow()
        if 0 <= row < len(self.entry.password_history):
            copy_fn(self.entry.password_history[row].password, "Old password")


class ImportPreviewDialog(Dialog):
    def __init__(self, path: str, new_entries: list[Entry], duplicates: int, warnings: list[str],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import passwords")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        lay.addWidget(label("Import passwords", heading=True))
        with_2fa = sum(1 for e in new_entries if e.totp)
        lines = [f"<b>{len(new_entries)}</b> new entries found"
                 + (f" ({with_2fa} with 2FA)" if with_2fa else "") + "."]
        if duplicates:
            lines.append(f"{duplicates} entries are already in your vault and will be skipped.")
        lay.addWidget(label("<br>".join(lines), wrap=True))
        if warnings:
            lay.addWidget(label("\n".join(warnings[:8]) + ("\n..." if len(warnings) > 8 else ""),
                                muted=True, wrap=True))
        lay.addWidget(label("The CSV file contains your passwords <b>unencrypted</b>. Delete it "
                            "once the import is done (and empty the Recycle Bin).",
                            warning=True, wrap=True))
        self.delete_check = QCheckBox("Delete the CSV file after importing")
        lay.addWidget(self.delete_check)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel")
        ok = button(f"Import {len(new_entries)} entries", primary=True)
        ok.setEnabled(bool(new_entries))
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
