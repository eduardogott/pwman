"""Dialogs for creating a vault, showing/using the recovery key and changing the master password."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..core import strength
from ..core.vault import FILE_SUFFIX, Vault, VaultError, WrongSecretError
from . import theme
from .services import Task
from .widgets import Card, Dialog, PasswordEdit, StrengthMeter, button, label

MIN_MASTER_LENGTH = 8
MIN_MASTER_QUALITY = 40  # "Fair"


class MasterPasswordFields(QWidget):
    """New password + confirmation with live strength feedback."""

    changed = Signal()

    def __init__(self, first_label="Master password", parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(8)
        self.pw = PasswordEdit("At least 8 characters - a passphrase is ideal")
        self.confirm = PasswordEdit("Type it again")
        self.meter = StrengthMeter()
        self.hint = label("", muted=True, wrap=True)
        self.caps = label("Caps Lock is on", error=True)
        self.caps.hide()
        self.pw.caps_lock_changed.connect(self.caps.setVisible)
        self.confirm.caps_lock_changed.connect(self.caps.setVisible)
        form.addRow(first_label, self.pw)
        form.addRow("", self.meter)
        form.addRow("", self.hint)
        form.addRow("Confirm", self.confirm)
        form.addRow("", self.caps)
        self.pw.textChanged.connect(self._update)
        self.confirm.textChanged.connect(self._update)
        self._update()

    def _update(self) -> None:
        pw = self.pw.text()
        report = strength.evaluate(pw) if pw else None
        self.meter.set_report(report)
        if not pw:
            self.hint.setText("Tip: 4-6 random words (try the passphrase generator) are easy to "
                              "remember and very hard to crack.")
        elif report.feedback:
            self.hint.setText(" ".join(report.feedback[:2]))
        else:
            self.hint.setText("Great choice.")
        self.changed.emit()

    def problem(self) -> str | None:
        pw = self.pw.text()
        if len(pw) < MIN_MASTER_LENGTH:
            return f"The master password must have at least {MIN_MASTER_LENGTH} characters."
        if strength.evaluate(pw).quality < MIN_MASTER_QUALITY:
            return "This master password is too easy to guess. Make it longer or less predictable."
        if pw != self.confirm.text():
            return "The two passwords don't match."
        return None

    def password(self) -> str:
        return self.pw.text()


RECOVERY_FILE_TEMPLATE = """PwMan recovery key
==================

Vault file : {vault}
Created    : {date}

Recovery key:

    {key}

What is this?
  If you ever forget your master password, open PwMan, click
  "Forgot master password?" and enter this key to set a new password.

Keep it safe:
  * Print it or store it offline (e.g. a USB stick in a drawer).
  * Do NOT keep it in the same place as your vault file.
  * Anyone who has both this key and your vault file can open your vault.
"""


class RecoveryKeyPanel(QWidget):
    confirmed = Signal(bool)

    def __init__(self, key: str, vault_path: Path, copy_fn: Callable[[str], None], parent=None):
        super().__init__(parent)
        self.key = key
        self.vault_path = vault_path
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(label("Save your recovery key", heading=True))
        lay.addWidget(label(
            "This key is the <b>only</b> way back into your vault if you forget the master "
            "password. It will not be shown again - store it somewhere safe and offline.",
            wrap=True))
        card = Card()
        key_lbl = label(key, selectable=True)
        key_lbl.setFont(theme.monospace_font(15))
        key_lbl.setAlignment(Qt.AlignCenter)
        key_lbl.setWordWrap(True)
        card.body.addWidget(key_lbl)
        lay.addWidget(card)
        row = QHBoxLayout()
        copy_btn = button("Copy", icon_name="copy")
        save_btn = button("Save as text file...", icon_name="import")
        copy_btn.clicked.connect(lambda: copy_fn(key))
        save_btn.clicked.connect(self._save)
        row.addWidget(copy_btn)
        row.addWidget(save_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.saved_lbl = label("", muted=True)
        lay.addWidget(self.saved_lbl)
        lay.addWidget(label("PwMan never uploads anything - if you lose both your master password "
                            "and this key, nobody can recover your data.", warning=True, wrap=True))
        self.check = QCheckBox("I have stored my recovery key in a safe place")
        self.check.toggled.connect(self.confirmed.emit)
        lay.addWidget(self.check)

    def _save(self) -> None:
        default = str(Path.home() / "PwMan recovery key.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Save recovery key", default, "Text files (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(RECOVERY_FILE_TEMPLATE.format(
                vault=self.vault_path, date=date.today().isoformat(), key=self.key), "utf-8")
        except OSError as exc:
            self.saved_lbl.setText(f"Could not save: {exc}")
            return
        self.saved_lbl.setText(f"Saved to {path}. Consider printing it, then moving the file "
                               "off this computer.")


def _busy(widget: QWidget, busy: bool) -> None:
    if busy:
        QApplication.setOverrideCursor(Qt.WaitCursor)
    else:
        QApplication.restoreOverrideCursor()
    widget.setEnabled(not busy)


class CreateVaultDialog(Dialog):
    def __init__(self, default_path: Path, copy_fn: Callable[[str], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create a new vault")
        self.setMinimumWidth(560)
        self.vault: Vault | None = None
        self.recovery_key: str | None = None
        self.copy_fn = copy_fn

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # page 1: password + location
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(label("Choose your master password", heading=True))
        lay.addWidget(label(
            "This is the one password you need to remember. It encrypts everything in your vault "
            "and is never stored anywhere - not even on this computer.", wrap=True, muted=True))
        self.fields = MasterPasswordFields()
        lay.addWidget(self.fields)
        loc_row = QHBoxLayout()
        self.path_edit = QLineEdit(str(default_path))
        browse = button("Browse...")
        browse.clicked.connect(self._browse)
        loc_row.addWidget(self.path_edit, 1)
        loc_row.addWidget(browse)
        form = QFormLayout()
        form.addRow("Vault file", loc_row)
        lay.addLayout(form)
        self.error = label("", error=True, wrap=True)
        lay.addWidget(self.error)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel")
        self.create_btn = button("Create vault", primary=True)
        self.create_btn.setDefault(True)
        cancel.clicked.connect(self.reject)
        self.create_btn.clicked.connect(self._create)
        row.addWidget(cancel)
        row.addWidget(self.create_btn)
        lay.addLayout(row)
        self.stack.addWidget(page)
        self.fields.changed.connect(lambda: self.error.setText(""))

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Vault location", self.path_edit.text(),
                                              f"PwMan vault (*{FILE_SUFFIX})")
        if path:
            if not path.lower().endswith(FILE_SUFFIX):
                path += FILE_SUFFIX
            self.path_edit.setText(path)

    def _create(self) -> None:
        problem = self.fields.problem()
        path = Path(self.path_edit.text().strip())
        if not problem and path.exists():
            problem = "A file already exists there. Choose another location or open that vault instead."
        if problem:
            self.error.setText(problem)
            return
        password = self.fields.password()
        _busy(self, True)
        self.create_btn.setText("Creating...")
        Task.run(self, lambda: Vault.create(path, password), self._created, self._failed)

    def _created(self, result) -> None:
        _busy(self, False)
        self.vault, self.recovery_key = result
        panel = RecoveryKeyPanel(self.recovery_key, self.vault.path, self.copy_fn)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(panel)
        row = QHBoxLayout()
        row.addStretch(1)
        done = button("Open my vault", primary=True)
        done.setEnabled(False)
        panel.confirmed.connect(done.setEnabled)
        done.clicked.connect(self.accept)
        row.addWidget(done)
        lay.addLayout(row)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def _failed(self, exc: Exception) -> None:
        _busy(self, False)
        self.create_btn.setText("Create vault")
        self.error.setText(str(exc) if isinstance(exc, VaultError) else f"Could not create the vault: {exc}")

    def reject(self) -> None:
        if self.vault is not None:
            # The vault exists already; closing just skips the confirmation checkbox.
            self.accept()
            return
        super().reject()


class RecoveryKeyDialog(Dialog):
    def __init__(self, key: str, vault_path: Path, copy_fn, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New recovery key")
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        panel = RecoveryKeyPanel(key, vault_path, copy_fn)
        lay.addWidget(panel)
        row = QHBoxLayout()
        row.addStretch(1)
        done = button("Done", primary=True)
        done.setEnabled(False)
        panel.confirmed.connect(done.setEnabled)
        done.clicked.connect(self.accept)
        row.addWidget(done)
        lay.addLayout(row)


class RecoverAccessDialog(Dialog):
    """Unlock with the recovery key, then set a new master password."""

    def __init__(self, vault_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recover access")
        self.setMinimumWidth(540)
        self.vault_path = vault_path
        self.vault: Vault | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setSpacing(12)
        l1.addWidget(label("Forgot your master password?", heading=True))
        l1.addWidget(label("Enter the recovery key you saved when you created this vault. "
                           "Upper/lower case and dashes don't matter.", wrap=True, muted=True))
        self.key_edit = QLineEdit()
        self.key_edit.setFont(theme.monospace_font(12))
        self.key_edit.setPlaceholderText("XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX")
        l1.addWidget(self.key_edit)
        self.err1 = label("", error=True, wrap=True)
        l1.addWidget(self.err1)
        l1.addStretch(1)
        r1 = QHBoxLayout()
        r1.addStretch(1)
        cancel = button("Cancel")
        self.next_btn = button("Continue", primary=True)
        self.next_btn.setDefault(True)
        cancel.clicked.connect(self.reject)
        self.next_btn.clicked.connect(self._check_key)
        r1.addWidget(cancel)
        r1.addWidget(self.next_btn)
        l1.addLayout(r1)
        self.stack.addWidget(p1)

        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setSpacing(12)
        l2.addWidget(label("Choose a new master password", heading=True))
        l2.addWidget(label("Your recovery key was accepted. Your existing recovery key keeps working; "
                           "you can create a new one later in Settings.", wrap=True, muted=True))
        self.fields = MasterPasswordFields("New password")
        l2.addWidget(self.fields)
        self.err2 = label("", error=True, wrap=True)
        l2.addWidget(self.err2)
        l2.addStretch(1)
        r2 = QHBoxLayout()
        r2.addStretch(1)
        self.set_btn = button("Set password and unlock", primary=True)
        self.set_btn.clicked.connect(self._set_password)
        r2.addWidget(self.set_btn)
        l2.addLayout(r2)
        self.stack.addWidget(p2)

    def _check_key(self) -> None:
        key = self.key_edit.text()
        _busy(self, True)
        Task.run(self, lambda: Vault.unlock_with_recovery_key(self.vault_path, key),
                 self._key_ok, self._key_failed)

    def _key_ok(self, vault: Vault) -> None:
        _busy(self, False)
        self.vault = vault
        self.stack.setCurrentIndex(1)
        self.set_btn.setDefault(True)
        self.fields.pw.setFocus()

    def _key_failed(self, exc: Exception) -> None:
        _busy(self, False)
        if isinstance(exc, WrongSecretError):
            self.err1.setText(str(exc) or "That recovery key is not correct for this vault.")
        else:
            self.err1.setText(str(exc))

    def _set_password(self) -> None:
        problem = self.fields.problem()
        if problem:
            self.err2.setText(problem)
            return
        password = self.fields.password()
        _busy(self, True)
        Task.run(self, lambda: self.vault.change_master_password(password),
                 lambda _: (_busy(self, False), self.accept()),
                 lambda exc: (_busy(self, False), self.err2.setText(f"Could not save: {exc}")))


class ChangePasswordDialog(Dialog):
    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.setWindowTitle("Change master password")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)
        lay.addWidget(label("Change master password", heading=True))
        form = QFormLayout()
        self.current = PasswordEdit("Your current master password")
        form.addRow("Current password", self.current)
        lay.addLayout(form)
        self.fields = MasterPasswordFields("New password")
        lay.addWidget(self.fields)
        lay.addWidget(label("Your recovery key keeps working. Encrypted backups made before this "
                            "change still open with the old password.", muted=True, wrap=True))
        self.error = label("", error=True, wrap=True)
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel")
        self.ok = button("Change password", primary=True)
        self.ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self._change)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)

    def _change(self) -> None:
        problem = self.fields.problem()
        if problem:
            self.error.setText(problem)
            return
        current, new = self.current.text(), self.fields.password()
        vault = self.vault

        def work():
            if not vault.verify_master_password(current):
                raise WrongSecretError("Your current master password is not correct.")
            vault.change_master_password(new)

        _busy(self, True)
        Task.run(self, work, lambda _: (_busy(self, False), self.accept()),
                 lambda exc: (_busy(self, False), self.error.setText(str(exc))))


class ConfirmPasswordDialog(Dialog):
    """Re-enter the master password before a sensitive action (e.g. export)."""

    def __init__(self, vault: Vault, title: str, message: str, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        lay.addWidget(label(title, subheading=True))
        lay.addWidget(label(message, wrap=True, warning=True))
        self.pw = PasswordEdit("Master password")
        lay.addWidget(self.pw)
        self.error = label("", error=True)
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel")
        ok = button("Continue", primary=True)
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._check)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def _check(self) -> None:
        pw = self.pw.text()
        _busy(self, True)
        Task.run(self, lambda: self.vault.verify_master_password(pw), self._done,
                 lambda exc: (_busy(self, False), self.error.setText(str(exc))))

    def _done(self, ok: bool) -> None:
        _busy(self, False)
        if ok:
            self.accept()
        else:
            self.error.setText("Incorrect master password.")
            self.pw.selectAll()
            self.pw.setFocus()

