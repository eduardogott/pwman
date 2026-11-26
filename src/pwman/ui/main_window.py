"""Main window: lock screen <-> vault view, menus and all user actions."""

from __future__ import annotations

import gc
import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QLockFile, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..config import AppConfig, data_dir
from ..core import csv_io, strength
from ..core.vault import FILE_SUFFIX, Vault, VaultError, WrongSecretError
from . import platform, theme
from .app_icon import app_icon, render
from .dialogs import HistoryDialog, ImportPreviewDialog, SecurityReportDialog, SettingsDialog
from .entry_dialog import EntryDialog
from .generator_dialog import GeneratorDialog
from .services import ActivityMonitor, SecureClipboard, Task
from .vault_dialogs import (
    ChangePasswordDialog, ConfirmPasswordDialog, CreateVaultDialog, RecoverAccessDialog,
    RecoveryKeyDialog,
)
from .vault_view import VaultView
from .widgets import PasswordEdit, Toast, button, label


class UnlockPage(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window_ = window
        self.failures = 0
        outer = QVBoxLayout(self)
        outer.addStretch(2)
        column = QWidget()
        column.setFixedWidth(400)
        lay = QVBoxLayout(column)
        lay.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QPixmap.fromImage(render(160)).scaled(
            80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(logo, alignment=Qt.AlignCenter)
        title = label(APP_NAME, heading=True)
        title.setStyleSheet("font-size: 22pt;")
        lay.addWidget(title, alignment=Qt.AlignCenter)
        self.subtitle = label("", muted=True, wrap=True)
        self.subtitle.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.subtitle)
        lay.addSpacing(8)

        # unlock form
        self.unlock_box = QWidget()
        ub = QVBoxLayout(self.unlock_box)
        ub.setContentsMargins(0, 0, 0, 0)
        ub.setSpacing(8)
        self.password = PasswordEdit("Master password")
        self.password.setMinimumHeight(38)
        self.password.returnPressed.connect(self._unlock)
        ub.addWidget(self.password)
        self.caps = label("Caps Lock is on", error=True)
        self.caps.hide()
        self.password.caps_lock_changed.connect(self.caps.setVisible)
        ub.addWidget(self.caps)
        self.error = label("", error=True, wrap=True)
        self.error.setAlignment(Qt.AlignCenter)
        self.error.hide()
        ub.addWidget(self.error)
        self.unlock_btn = button("Unlock", primary=True)
        self.unlock_btn.setMinimumHeight(38)
        self.unlock_btn.clicked.connect(self._unlock)
        ub.addWidget(self.unlock_btn)
        self.forgot = button("Forgot master password? Use your recovery key", link=True)
        self.forgot.clicked.connect(window.recover_access)
        ub.addWidget(self.forgot, alignment=Qt.AlignCenter)
        lay.addWidget(self.unlock_box)

        # first-run
        self.welcome_box = QWidget()
        wb = QVBoxLayout(self.welcome_box)
        wb.setContentsMargins(0, 0, 0, 0)
        wb.setSpacing(8)
        welcome = label("Welcome! Create a vault to start storing your passwords and 2FA codes "
                        "securely on this computer.", wrap=True)
        welcome.setAlignment(Qt.AlignCenter)
        wb.addWidget(welcome)
        wb.addSpacing(6)
        create = button("Create a new vault", primary=True)
        create.setMinimumHeight(38)
        create.clicked.connect(window.create_vault)
        wb.addWidget(create)
        open_btn = button("Open an existing vault file...")
        open_btn.clicked.connect(window.open_vault_file)
        wb.addWidget(open_btn)
        lay.addWidget(self.welcome_box)

        lay.addSpacing(10)
        self.links = QWidget()
        links = QVBoxLayout(self.links)
        links.setContentsMargins(0, 0, 0, 0)
        links.setSpacing(0)
        other = button("Open another vault...", link=True)
        other.clicked.connect(window.open_vault_file)
        new = button("Create a new vault...", link=True)
        new.clicked.connect(window.create_vault)
        links.addWidget(other, alignment=Qt.AlignCenter)
        links.addWidget(new, alignment=Qt.AlignCenter)
        lay.addWidget(self.links)
        centered = QHBoxLayout()
        centered.addStretch(1)
        centered.addWidget(column)
        centered.addStretch(1)
        outer.addLayout(centered)
        outer.addStretch(3)
        foot = label("Offline · encrypted with AES-256 + Argon2id · your data never leaves "
                     "this computer", muted=True)
        outer.addWidget(foot, alignment=Qt.AlignCenter)

    def refresh(self, path: Path) -> None:
        exists = Vault.exists(path)
        self.unlock_box.setVisible(exists)
        self.links.setVisible(exists)
        self.welcome_box.setVisible(not exists)
        self.subtitle.setText(path.name if exists else "Your offline password manager")
        self.subtitle.setToolTip(str(path) if exists else "")
        self.password.clear()
        self.error.hide()
        self.set_busy(False)
        if exists:
            QTimer.singleShot(0, self.password.setFocus)

    def set_busy(self, busy: bool) -> None:
        self.password.setEnabled(not busy)
        self.unlock_btn.setEnabled(not busy)
        self.unlock_btn.setText("Unlocking..." if busy else "Unlock")

    def show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.show()
        self.password.selectAll()
        self.password.setFocus()

    def _unlock(self) -> None:
        if self.password.text():
            self.window_.unlock(self.password.text())


class WindowGuard(QObject):
    """Applies screenshot protection to every window PwMan shows (Windows only)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = False

    def eventFilter(self, obj, event):  # noqa: N802
        if self.enabled and event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
            platform.set_capture_protection(int(obj.winId()), True)
        return False


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.vault: Vault | None = None
        self._lock_file: QLockFile | None = None
        self._session_registered = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1120, 720)
        self.setMinimumSize(860, 560)
        if config.window_geometry:
            try:
                self.restoreGeometry(QByteArray.fromHex(config.window_geometry.encode()))
            except Exception:
                pass

        self.clipboard = SecureClipboard(self)
        self.activity = ActivityMonitor(self)
        self.activity.idle.connect(lambda: self.lock(reason="Locked after inactivity."))
        self.guard = WindowGuard(self)
        app = QApplication.instance()
        app.installEventFilter(self.activity)
        app.installEventFilter(self.guard)

        self.stack = QStackedWidget()
        self.unlock_page = UnlockPage(self)
        self.vault_view = VaultView()
        self.stack.addWidget(self.unlock_page)
        self.stack.addWidget(self.vault_view)
        self.setCentralWidget(self.stack)
        self.toast = Toast(self)
        self._build_menus()
        self._connect_view()
        self.show_lock_screen()
        try:
            QApplication.styleHints().colorSchemeChanged.connect(self._system_theme_changed)
        except AttributeError:
            pass

    # ------------------------------------------------------------------ menus
    def _action(self, menu, text, slot, shortcut=None, unlocked_only=True) -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        if unlocked_only:
            self._unlocked_actions.append(act)
        return act

    def _build_menus(self) -> None:
        self._unlocked_actions: list[QAction] = []
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._action(f, "New vault...", self.create_vault, unlocked_only=False)
        self._action(f, "Open vault...", self.open_vault_file, unlocked_only=False)
        f.addSeparator()
        self._action(f, "Import passwords (CSV)...", self.import_csv)
        self._action(f, "Export passwords (CSV)...", self.export_csv)
        self._action(f, "Save encrypted backup copy...", self.backup_copy)
        self._action(f, "Open backups folder", self.open_backups)
        f.addSeparator()
        self._action(f, "Lock", self.lock, "Ctrl+L")
        self._action(f, "Quit", self.close, "Ctrl+Q", unlocked_only=False)
        e = mb.addMenu("&Entry")
        v = self.vault_view
        self._action(e, "New entry", self.new_entry, "Ctrl+N")
        self._action(e, "Edit entry", lambda: v._emit_current(v.edit_requested), "Ctrl+E")
        self._action(e, "Delete entry", lambda: v._emit_current(v.delete_requested), "Del")
        e.addSeparator()
        self._action(e, "Copy username", v.copy_username, "Ctrl+B")
        self._action(e, "Copy password\t(Ctrl+C in the list)", v.copy_password)
        self._action(e, "Copy 2FA code", v.copy_totp, "Ctrl+T")
        self._action(e, "Open website", v.open_url, "Ctrl+U")
        e.addSeparator()
        self._action(e, "Find...", v.focus_search, "Ctrl+F")
        t = mb.addMenu("&Tools")
        self._action(t, "Password generator...", self.open_generator, "Ctrl+G", unlocked_only=False)
        self._action(t, "Security report...", self.open_security_report)
        self._action(t, "Settings...", self.open_settings, "Ctrl+,")
        h = mb.addMenu("&Help")
        self._action(h, "Keyboard shortcuts", self.show_shortcuts, unlocked_only=False)
        self._action(h, "About PwMan", self.show_about, unlocked_only=False)

    def _connect_view(self) -> None:
        v = self.vault_view
        v.new_requested.connect(self.new_entry)
        v.edit_requested.connect(self.edit_entry)
        v.delete_requested.connect(self.delete_entry)
        v.copy_requested.connect(self.copy_secret)
        v.open_url_requested.connect(self.open_url)
        v.favorite_changed.connect(self.set_favorite)
        v.history_requested.connect(self.show_history)
        v.import_requested.connect(self.import_csv)
        v.generator_requested.connect(self.open_generator)
        v.security_requested.connect(self.open_security_report)
        v.settings_requested.connect(self.open_settings)
        v.lock_requested.connect(self.lock)

    # ------------------------------------------------------------------ state
    @property
    def unlocked(self) -> bool:
        return self.vault is not None and not self.vault.is_locked

    def show_lock_screen(self) -> None:
        for act in self._unlocked_actions:
            act.setEnabled(False)
        self.unlock_page.refresh(self.config.effective_vault_path)
        self.stack.setCurrentWidget(self.unlock_page)
        self.setWindowTitle(APP_NAME)

    def unlock(self, password: str) -> None:
        path = self.config.effective_vault_path
        self.unlock_page.set_busy(True)
        Task.run(self, lambda: Vault.unlock(path, password), self._on_unlocked, self._unlock_failed)

    def _unlock_failed(self, exc: Exception) -> None:
        self.unlock_page.set_busy(False)
        if isinstance(exc, WrongSecretError):
            self.unlock_page.failures += 1
            msg = "Incorrect master password."
            if self.unlock_page.failures >= 3:
                msg += " Forgot it? Use your recovery key below."
            self.unlock_page.show_error(msg)
        elif isinstance(exc, VaultError):
            self.unlock_page.show_error(str(exc))
        else:
            self.unlock_page.show_error(f"Could not open the vault: {exc}")

    def _acquire_lock_file(self, path: Path) -> bool:
        lock = QLockFile(str(path) + ".lock")
        lock.setStaleLockTime(0)
        if not lock.tryLock(200):
            return False
        self._lock_file = lock
        return True

    def _release_lock_file(self) -> None:
        if self._lock_file is not None:
            self._lock_file.unlock()
            self._lock_file = None

    def _on_unlocked(self, vault: Vault) -> None:
        self.unlock_page.set_busy(False)
        if not self._acquire_lock_file(vault.path):
            vault.lock()
            self.unlock_page.show_error("This vault is already open in another PwMan window.")
            return
        self.unlock_page.failures = 0
        self.vault = vault
        self.config.remember_vault(vault.path)
        self.config.save()
        for act in self._unlocked_actions:
            act.setEnabled(True)
        self._apply_vault_settings()
        self.vault_view.set_entries(vault.entries, vault.settings.password_max_age_days)
        self.stack.setCurrentWidget(self.vault_view)
        self.setWindowTitle(f"{vault.path.stem} - {APP_NAME}")
        self.unlock_page.password.clear()

    def _apply_vault_settings(self) -> None:
        s = self.vault.settings
        self.activity.start(s.auto_lock_minutes * 60)
        self.guard.enabled = s.screen_capture_protection and platform.IS_WINDOWS
        if platform.IS_WINDOWS:
            for w in QApplication.topLevelWidgets():
                if w.isWindow() and w.isVisible():
                    platform.set_capture_protection(int(w.winId()), self.guard.enabled)

    def lock(self, reason: str | None = None) -> None:
        if self.vault is None:
            return
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible():
                w.reject()
        self.clipboard.clear_if_ours()
        self.toast.hide()
        self.activity.stop()
        self.vault.lock()
        self.vault = None
        self.vault_view.clear()
        strength.clear_cache()
        self._release_lock_file()
        self.show_lock_screen()
        if reason:
            self.unlock_page.subtitle.setText(f"{self.config.effective_vault_path.name}\n{reason}")
        gc.collect()

    def save(self) -> bool:
        try:
            self.vault.save()
            return True
        except Exception as exc:  # disk full, permissions, file locked...
            QMessageBox.critical(self, "Could not save",
                                 f"Your changes could not be saved to disk:\n\n{exc}\n\n"
                                 "They are kept in memory - fix the problem and make another change "
                                 "to retry, or save a backup copy from the File menu.")
            return False

    def reload_view(self, select: str | None = None) -> None:
        if self.unlocked:
            self.vault_view.set_entries(self.vault.entries, self.vault.settings.password_max_age_days,
                                        select)

    # ------------------------------------------------------------------ vault files
    def _suggest_new_path(self) -> Path:
        base = data_dir()
        candidate = base / f"vault{FILE_SUFFIX}"
        n = 2
        while candidate.exists():
            candidate = base / f"vault-{n}{FILE_SUFFIX}"
            n += 1
        return candidate

    def create_vault(self) -> None:
        if self.unlocked:
            self.lock()
        dlg = CreateVaultDialog(self._suggest_new_path(), self._copy_recovery_key, self)
        if dlg.exec() == QDialog.Accepted and dlg.vault is not None:
            self._on_unlocked(dlg.vault)
            self.toast.show_message("Vault created. Add your first password with “New entry”.")

    def open_vault_file(self) -> None:
        start = str(self.config.effective_vault_path.parent)
        path, _ = QFileDialog.getOpenFileName(self, "Open vault", start,
                                              f"PwMan vault (*{FILE_SUFFIX});;All files (*)")
        if not path:
            return
        if self.unlocked:
            self.lock()
        self.config.remember_vault(path)
        self.config.save()
        self.show_lock_screen()

    def recover_access(self) -> None:
        dlg = RecoverAccessDialog(self.config.effective_vault_path, self)
        if dlg.exec() == QDialog.Accepted and dlg.vault is not None:
            self._on_unlocked(dlg.vault)
            self.toast.show_message("New master password set. Your vault is unlocked.")

    def _copy_recovery_key(self, key: str) -> None:
        self.clipboard.copy(key, 120)
        self.toast.show_message("Recovery key copied - paste it somewhere safe. "
                                "The clipboard clears in 2 minutes.", 4000)

    # ------------------------------------------------------------------ entries
    def _reuse_lookup(self, password: str, exclude_id: str | None) -> int:
        if not self.unlocked:
            return 0
        return sum(1 for e in self.vault.entries if e.password == password and e.id != exclude_id)

    def new_entry(self) -> None:
        if not self.unlocked:
            return
        dlg = EntryDialog(self.config, None, self.vault.settings.password_max_age_days,
                          self._reuse_lookup, self)
        accepted = dlg.exec() == QDialog.Accepted
        self.config.save()
        if not accepted or not self.unlocked:
            return
        entry = dlg.build_entry()
        self.vault.add(entry)
        if self.save():
            self.toast.show_message(f"“{entry.title}” saved.")
        self.reload_view(entry.id)

    def edit_entry(self, entry_id: str) -> None:
        entry = self.vault.get(entry_id) if self.unlocked else None
        if entry is None:
            return
        dlg = EntryDialog(self.config, entry, self.vault.settings.password_max_age_days,
                          self._reuse_lookup, self)
        accepted = dlg.exec() == QDialog.Accepted
        self.config.save()
        if not accepted or not self.unlocked:
            return
        dlg.apply_to(entry)
        if self.save():
            self.toast.show_message("Changes saved.")
        self.reload_view(entry.id)

    def delete_entry(self, entry_id: str) -> None:
        entry = self.vault.get(entry_id) if self.unlocked else None
        if entry is None:
            return
        answer = QMessageBox.question(
            self, "Delete entry",
            f"Delete “{entry.title}”?\n\nThis cannot be undone (older encrypted backups "
            "still contain it).", QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes or not self.unlocked:
            return
        self.vault.remove(entry_id)
        self.save()
        self.reload_view()
        self.toast.show_message(f"“{entry.title}” deleted.")

    def set_favorite(self, entry_id: str, on: bool) -> None:
        entry = self.vault.get(entry_id) if self.unlocked else None
        if entry:
            entry.favorite = on
            entry.touch()
            self.save()
            self.reload_view(entry_id)

    def show_history(self, entry_id: str) -> None:
        entry = self.vault.get(entry_id) if self.unlocked else None
        if entry:
            HistoryDialog(entry, self.copy_secret, self).exec()

    def copy_secret(self, value: str, what: str) -> None:
        if not value:
            return
        secret = what not in ("Website address",)
        seconds = self.vault.settings.clipboard_clear_seconds if self.unlocked else 30
        self.clipboard.copy(value, seconds, secret=secret)
        suffix = f" - clipboard clears in {seconds} s" if secret and seconds else ""
        self.toast.show_message(f"{what} copied{suffix}")

    def open_url(self, url: str) -> None:
        qurl = QUrl.fromUserInput(url.strip())
        if qurl.scheme().lower() not in ("http", "https"):
            QMessageBox.information(self, "Open website",
                                    f"Only http:// and https:// addresses are opened.\n\n{url}")
            return
        QDesktopServices.openUrl(qurl)

    # ------------------------------------------------------------------ import / export
    def import_csv(self) -> None:
        if not self.unlocked:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import passwords from CSV", str(Path.home()),
                                              "CSV files (*.csv);;All files (*)")
        if not path or not self.unlocked:
            return
        try:
            result = csv_io.parse_csv_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        key = lambda e: (e.title.casefold(), e.username.casefold(), e.password)  # noqa: E731
        seen = {key(e) for e in self.vault.entries}
        new, dupes = [], 0
        for e in result.entries:
            if key(e) in seen:
                dupes += 1
            else:
                seen.add(key(e))
                new.append(e)
        dlg = ImportPreviewDialog(path, new, dupes, result.warnings, self)
        if dlg.exec() != QDialog.Accepted or not self.unlocked:
            return
        self.vault.entries.extend(new)
        if self.save():
            msg = f"Imported {len(new)} entries."
            if dlg.delete_check.isChecked():
                try:
                    os.remove(path)
                    msg += " The CSV file was deleted."
                except OSError as exc:
                    msg += f" Could not delete the CSV file: {exc}"
            self.toast.show_message(msg, 4000)
        self.reload_view()

    def export_csv(self) -> None:
        if not self.unlocked:
            return
        dlg = ConfirmPasswordDialog(
            self.vault, "Export passwords",
            "The exported file will contain ALL your passwords in plain text. Anyone who can read "
            "it can log in to your accounts. Delete it as soon as you are done.", self)
        if dlg.exec() != QDialog.Accepted or not self.unlocked:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export passwords",
                                              str(Path.home() / "pwman-export.csv"), "CSV files (*.csv)")
        if not path or not self.unlocked:
            return
        try:
            Path(path).write_text(csv_io.export_csv_text(self.vault.entries), "utf-8-sig")
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.toast.show_message(f"Exported {len(self.vault.entries)} entries.")

    def backup_copy(self) -> None:
        if not self.unlocked:
            return
        default = Path.home() / f"{self.vault.path.stem}-backup{FILE_SUFFIX}"
        path, _ = QFileDialog.getSaveFileName(self, "Save encrypted backup copy", str(default),
                                              f"PwMan vault (*{FILE_SUFFIX})")
        if not path or not self.unlocked:
            return
        try:
            self.vault.save_copy(path)
        except OSError as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))
            return
        self.toast.show_message("Encrypted backup saved. It opens with your master password "
                                "or recovery key.", 4000)

    def open_backups(self) -> None:
        if not self.unlocked:
            return
        folder = self.vault.backup_dir
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ------------------------------------------------------------------ tools
    def open_generator(self) -> None:
        dlg = GeneratorDialog(self.config, copy_callback=lambda v: self.copy_secret(v, "Password"),
                              parent=self)
        dlg.exec()
        self.config.save()

    def open_security_report(self) -> None:
        if not self.unlocked:
            return
        report = self.vault_view.report
        dlg = SecurityReportDialog(self.vault.entries, report,
                                   self.vault.settings.password_max_age_days, self)
        dlg.entry_selected.connect(self.vault_view.select_entry)
        dlg.exec()

    def open_settings(self) -> None:
        if not self.unlocked:
            return
        dlg = SettingsDialog(self.vault.settings, self.config.theme, self)
        dlg.change_password_requested.connect(lambda: self.change_master_password(dlg))
        dlg.new_recovery_key_requested.connect(lambda: self.new_recovery_key(dlg))
        if dlg.exec() != QDialog.Accepted or not self.unlocked:
            return
        dlg.apply_to(self.vault.settings)
        if dlg.theme_mode() != self.config.theme:
            self.config.theme = dlg.theme_mode()
            self.config.save()
            self.apply_theme()
        if self.save():
            self.toast.show_message("Settings saved.")
        self._apply_vault_settings()
        self.reload_view()

    def change_master_password(self, parent=None) -> None:
        if not self.unlocked:
            return
        dlg = ChangePasswordDialog(self.vault, parent or self)
        if dlg.exec() == QDialog.Accepted:
            self.toast.show_message("Master password changed.")

    def new_recovery_key(self, parent=None) -> None:
        if not self.unlocked:
            return
        answer = QMessageBox.question(
            parent or self, "Create new recovery key",
            "Create a new recovery key?\n\nYour current recovery key will stop working immediately.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes or not self.unlocked:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            key = self.vault.regenerate_recovery_key()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Could not create a new recovery key: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        RecoveryKeyDialog(key, self.vault.path, self._copy_recovery_key, parent or self).exec()

    def apply_theme(self) -> None:
        theme.apply(QApplication.instance(), self.config.theme)
        if self.unlocked:
            self.reload_view()

    def _system_theme_changed(self, *_):
        if self.config.theme == "system":
            self.apply_theme()

    def show_shortcuts(self) -> None:
        QMessageBox.information(self, "Keyboard shortcuts", (
            "Ctrl+F\tSearch\n"
            "Ctrl+N\tNew entry\n"
            "Ctrl+E / Enter\tEdit selected entry\n"
            "Del\tDelete selected entry\n"
            "Ctrl+B\tCopy username\n"
            "Ctrl+C\tCopy password (when the list has focus)\n"
            "Ctrl+T\tCopy 2FA code\n"
            "Ctrl+U\tOpen website\n"
            "Ctrl+G\tPassword generator\n"
            "Ctrl+L\tLock\n"
            "Ctrl+Q\tQuit"))

    def show_about(self) -> None:
        QMessageBox.about(self, f"About {APP_NAME}", (
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>An offline password manager with built-in 2FA codes.</p>"
            "<p>PwMan never connects to the internet. Your vault is encrypted with AES-256-GCM "
            "using a key derived from your master password with Argon2id, and it is stored only "
            "on this computer.</p>"
            f"<p>Data folder:<br><code>{data_dir()}</code></p>"
            "<p>Passphrase wordlist © Electronic Frontier Foundation, CC BY 3.0.</p>"))

    # ------------------------------------------------------------------ window events
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._session_registered:
            self._session_registered = True
            platform.register_session_notifications(int(self.winId()))

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if (event.type() == QEvent.WindowStateChange and self.isMinimized() and self.unlocked
                and self.vault.settings.lock_on_minimize):
            QTimer.singleShot(0, self.lock)

    if platform.IS_WINDOWS:
        def nativeEvent(self, event_type, message):  # noqa: N802
            if (self.unlocked and self.vault.settings.lock_on_system_lock
                    and platform.is_session_lock_message(event_type, message)):
                QTimer.singleShot(0, lambda: self.lock(reason="Locked because the computer was locked."))
            return super().nativeEvent(event_type, message)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast.move((self.width() - self.toast.width()) // 2,
                            self.height() - self.toast.height() - 36)

    def closeEvent(self, event):  # noqa: N802
        self.config.window_geometry = bytes(self.saveGeometry().toHex()).decode()
        self.config.save()
        self.lock()
        self.clipboard.clear_if_ours()
        super().closeEvent(event)
