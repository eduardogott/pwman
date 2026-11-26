"""Add / edit entry dialog."""

from __future__ import annotations

import copy
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget,
)

from ..config import AppConfig
from ..core import strength, totp
from ..core.csv_io import _title_from_url
from ..core.models import Entry, TotpConfig, now_iso
from . import theme
from .generator_dialog import GeneratorDialog
from .services import decode_qr_codes, grab_screens
from .widgets import (
    Dialog, PasswordEdit, StrengthMeter, TotpRing, button, label, set_invalid, tool_button,
)


class EntryDialog(Dialog):
    def __init__(self, config: AppConfig, entry: Entry | None, max_age_days: int,
                 reuse_lookup: Callable[[str, str | None], int], parent=None):
        super().__init__(parent)
        self.config = config
        self.original = entry
        self.max_age_days = max_age_days
        self.reuse_lookup = reuse_lookup
        self._totp: TotpConfig | None = copy.deepcopy(entry.totp) if entry else None
        self._totp_error = ""
        self.setWindowTitle("Edit entry" if entry else "New entry")
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)
        root.addWidget(label("Edit entry" if entry else "New entry", heading=True))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("e.g. Gmail, Netflix, Bank")
        form.addRow("Name", self.title_edit)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Username or e-mail")
        form.addRow("Username", self.username_edit)

        # password + generate
        self.password_edit = PasswordEdit("Password")
        gen_btn = button("Generate", icon_name="dice", tooltip="Open the password generator")
        gen_btn.clicked.connect(self._open_generator)
        pw_row = QHBoxLayout()
        pw_row.addWidget(self.password_edit, 1)
        pw_row.addWidget(gen_btn)
        form.addRow("Password", pw_row)
        self.meter = StrengthMeter()
        self.pw_feedback = label("", muted=True, wrap=True)
        self.caps_label = label("Caps Lock is on", error=True)
        self.caps_label.hide()
        self.password_edit.caps_lock_changed.connect(self.caps_label.setVisible)
        meter_box = QVBoxLayout()
        meter_box.setSpacing(2)
        meter_box.addWidget(self.meter)
        meter_box.addWidget(self.pw_feedback)
        meter_box.addWidget(self.caps_label)
        form.addRow("", meter_box)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com")
        form.addRow("Website", self.url_edit)

        # 2FA
        self.totp_edit = QLineEdit()
        self.totp_edit.setPlaceholderText("Setup key or otpauth:// link (optional)")
        self.totp_edit.setFont(theme.monospace_font())
        scan_btn = tool_button("qr", "Scan a QR code that is visible on your screen")
        clip_btn = tool_button("clipboard", "Read a QR code from an image in the clipboard\n"
                                            "(tip: Win+Shift+S to snip the QR code first)")
        file_btn = tool_button("image", "Read a QR code from an image file")
        scan_btn.clicked.connect(self._scan_screen)
        clip_btn.clicked.connect(self._scan_clipboard)
        file_btn.clicked.connect(self._scan_file)
        totp_row = QHBoxLayout()
        totp_row.addWidget(self.totp_edit, 1)
        for b in (scan_btn, clip_btn, file_btn):
            totp_row.addWidget(b)
        form.addRow("2FA", totp_row)
        self.totp_preview = QWidget()
        prev = QHBoxLayout(self.totp_preview)
        prev.setContentsMargins(0, 0, 0, 0)
        self.totp_ring = TotpRing()
        self.totp_code = label("")
        self.totp_code.setFont(theme.monospace_font(13))
        self.totp_info = label("", muted=True)
        prev.addWidget(self.totp_ring)
        prev.addWidget(self.totp_code)
        prev.addWidget(self.totp_info, 1)
        self.totp_msg = label("", muted=True, wrap=True)
        totp_box = QVBoxLayout()
        totp_box.setSpacing(2)
        totp_box.addWidget(self.totp_preview)
        totp_box.addWidget(self.totp_msg)
        form.addRow("", totp_box)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Security questions, PINs, recovery codes...")
        self.notes_edit.setFixedHeight(90)
        form.addRow("Notes", self.notes_edit)

        self.favorite_check = QCheckBox("Favorite")
        form.addRow("", self.favorite_check)
        root.addLayout(form)

        self.error = label("", error=True, wrap=True)
        self.error.hide()
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = button("Cancel")
        self.save_btn = button("Save", primary=True)
        self.save_btn.setDefault(True)
        cancel.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_btn)
        root.addLayout(buttons)

        if entry:
            self.title_edit.setText(entry.title)
            self.username_edit.setText(entry.username)
            self.password_edit.setText(entry.password)
            self.url_edit.setText(entry.url)
            self.notes_edit.setPlainText(entry.notes)
            self.favorite_check.setChecked(entry.favorite)
            if entry.totp:
                self.totp_edit.setText(self._totp_display(entry.totp))
        self._original_totp_text = self.totp_edit.text()

        self.password_edit.textChanged.connect(self._update_strength)
        self.username_edit.textChanged.connect(self._update_strength)
        self.totp_edit.textChanged.connect(self._totp_changed)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(500)
        self._update_strength()
        self._totp_changed()
        self.title_edit.setFocus()

    # ------------------------------------------------------------------ password
    def _open_generator(self) -> None:
        dlg = GeneratorDialog(self.config, use_button=True, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.value():
            self.password_edit.setText(dlg.value())
            self.password_edit.set_visible(True)

    def _update_strength(self) -> None:
        pw = self.password_edit.text()
        changed_at = self.original.password_changed_at if (
            self.original and pw == self.original.password) else now_iso()
        reused = self.reuse_lookup(pw, self.original.id if self.original else None) if pw else 0
        report = strength.evaluate(pw, changed_at=changed_at, max_age_days=self.max_age_days,
                                   reused_count=reused,
                                   user_inputs=(self.username_edit.text(), self.title_edit.text()))
        self.meter.set_report(report if pw else None)
        self.pw_feedback.setText(" ".join(report.feedback[:2]) if pw else "")
        self.refit()

    # ------------------------------------------------------------------ 2FA
    @staticmethod
    def _totp_display(cfg: TotpConfig) -> str:
        if (cfg.algorithm, cfg.digits, cfg.period) == ("SHA1", 6, 30):
            return " ".join(cfg.secret[i:i + 4] for i in range(0, len(cfg.secret), 4))
        return totp.to_otpauth_uri(cfg)

    def _totp_changed(self) -> None:
        text = self.totp_edit.text().strip()
        self._totp_error = ""
        if not text:
            self._totp = None
        elif self.original and self.original.totp and text == self._original_totp_text.strip():
            self._totp = copy.deepcopy(self.original.totp)
        else:
            try:
                self._totp = totp.parse_any(text)[0]
            except ValueError as exc:
                self._totp = None
                self._totp_error = str(exc)
        set_invalid(self.totp_edit, bool(self._totp_error))
        if self._totp_error:
            self.totp_msg.setText(self._totp_error)
            self.totp_msg.setProperty("error", True)
        else:
            self.totp_msg.setText("" if self._totp or text else
                                  "Paste the setup key a website shows when you enable two-factor "
                                  "authentication, or scan its QR code.")
            self.totp_msg.setProperty("error", False)
        self.totp_msg.style().unpolish(self.totp_msg)
        self.totp_msg.style().polish(self.totp_msg)
        self.totp_preview.setVisible(self._totp is not None)
        if self._totp and not self.username_edit.text() and self._totp.account:
            self.username_edit.setText(self._totp.account)
        if self._totp and not self.title_edit.text() and self._totp.issuer:
            self.title_edit.setText(self._totp.issuer)
        self.save_btn.setEnabled(not self._totp_error)
        self._tick()
        self.refit()

    def _tick(self) -> None:
        if not self._totp:
            return
        try:
            code = totp.generate(self._totp)
        except ValueError:
            return
        self.totp_code.setText(totp.format_code(code))
        self.totp_ring.set_time(totp.seconds_remaining(self._totp), self._totp.period)
        bits = []
        if self._totp.issuer:
            bits.append(self._totp.issuer)
        if (self._totp.algorithm, self._totp.digits, self._totp.period) != ("SHA1", 6, 30):
            bits.append(f"{self._totp.algorithm}, {self._totp.digits} digits, {self._totp.period}s")
        self.totp_info.setText("  ·  ".join(bits) if bits else "Code preview - check it matches the website")

    def _use_qr_texts(self, texts: list[str]) -> None:
        candidates: list[tuple[str, TotpConfig]] = []
        for text in texts:
            try:
                for cfg in totp.parse_any(text):
                    name = " - ".join(p for p in (cfg.issuer, cfg.account) if p) or "Unnamed account"
                    candidates.append((name, cfg))
            except ValueError:
                continue
        if not candidates:
            msg = ("A QR code was found, but it is not a 2FA setup code." if texts
                   else "No QR code found. Make sure the whole QR code is visible and not too small.")
            self.totp_msg.setText(msg)
            return
        chosen = candidates[0][1]
        if len(candidates) > 1:
            names = [n for n, _ in candidates]
            name, ok = QInputDialog.getItem(self, "Choose account",
                                            "Several 2FA accounts were found. Which one is this entry?",
                                            names, 0, False)
            if not ok:
                return
            chosen = candidates[names.index(name)][1]
        self.totp_edit.setText(totp.to_otpauth_uri(chosen))

    def _scan_screen(self) -> None:
        windows = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
        for w in windows:
            w.setWindowOpacity(0.0)
        QApplication.processEvents()

        def grab():
            try:
                texts = [t for img in grab_screens() for t in decode_qr_codes(img)]
            finally:
                for w in windows:
                    w.setWindowOpacity(1.0)
            self._use_qr_texts(texts)

        QTimer.singleShot(350, grab)

    def _scan_clipboard(self) -> None:
        image = QGuiApplication.clipboard().image()
        if image.isNull():
            self.totp_msg.setText("The clipboard has no image. Snip the QR code first "
                                  "(Windows: Win+Shift+S), then click this button again.")
            return
        self._use_qr_texts(decode_qr_codes(image))

    def _scan_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open QR code image", "",
                                              "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if path:
            self._use_qr_texts(decode_qr_codes(QImage(path)))

    # ------------------------------------------------------------------ save
    def _save(self) -> None:
        title = self.title_edit.text().strip() or _title_from_url(self.url_edit.text().strip())
        if not title:
            self.error.setText("Please give this entry a name.")
            self.error.show()
            set_invalid(self.title_edit, True)
            self.title_edit.setFocus()
            return
        if self._totp_error:
            return
        self.title_edit.setText(title)
        self.accept()

    def apply_to(self, entry: Entry) -> None:
        entry.title = self.title_edit.text().strip()
        entry.username = self.username_edit.text().strip()
        entry.set_password(self.password_edit.text())
        entry.url = self.url_edit.text().strip()
        entry.notes = self.notes_edit.toPlainText()
        entry.totp = self._totp
        entry.favorite = self.favorite_check.isChecked()
        entry.touch()

    def build_entry(self) -> Entry:
        entry = Entry(title="")
        entry.password = self.password_edit.text()
        self.apply_to(entry)
        return entry

    def done(self, result):  # noqa: D401 - Qt override
        self._timer.stop()
        super().done(result)
