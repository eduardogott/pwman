"""End-to-end UI tests (run headless with QT_QPA_PLATFORM=offscreen)."""

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from conftest import FAST_KDF  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_home, monkeypatch):
    import pwman.core.vault as vault_mod
    from pwman.config import AppConfig
    from pwman.ui import theme
    from pwman.ui.main_window import MainWindow

    monkeypatch.setattr(vault_mod, "DEFAULT_KDF", FAST_KDF)  # fast Argon2 for tests
    theme.apply(app, "light")
    win = MainWindow(AppConfig.load())
    win.show()
    yield win
    win.close()


def wait_until(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def create_vault(win, password="Velvet-Harbor-Quartz-Lantern7"):
    from pwman.ui.vault_dialogs import CreateVaultDialog

    dlg = CreateVaultDialog(win._suggest_new_path(), win._copy_recovery_key, win)
    dlg.show()
    dlg.fields.pw.setText(password)
    dlg.fields.confirm.setText(password)
    dlg.create_btn.click()
    wait_until(lambda: dlg.vault is not None)
    win._on_unlocked(dlg.vault)
    dlg.close()
    return dlg


def test_full_flow(window, tmp_home):
    from pwman.core.models import Entry, TotpConfig
    from pwman.core.vault import Vault

    assert window.unlock_page.welcome_box.isVisibleTo(window)
    dlg = create_vault(window)
    assert window.unlocked and window.stack.currentWidget() is window.vault_view

    entry = Entry(title="GitHub", username="me", password="Summer2024!",
                  totp=TotpConfig(secret="JBSWY3DPEHPK3PXP"))
    window.vault.add(entry)
    assert window.save()
    window.reload_view(entry.id)
    assert window.vault_view.selected_entry().id == entry.id
    assert window.vault_view.report.weak == [entry]
    assert window.vault_view.detail.totp_row.value.text().replace(" ", "").isdigit()

    # copy -> clipboard, then auto-clear
    window.vault.settings.clipboard_clear_seconds = 1
    window.vault_view.copy_password()
    assert QGuiApplication.clipboard().text() == "Summer2024!"
    wait_until(lambda: QGuiApplication.clipboard().text() == "", timeout=3)

    # lock wipes everything
    window.lock()
    assert window.vault is None and window.vault_view.model.rowCount() == 0
    assert window.stack.currentWidget() is window.unlock_page

    # wrong password, then right password
    window.unlock("wrong password")
    wait_until(lambda: window.unlock_page.error.isVisibleTo(window))
    assert "Incorrect" in window.unlock_page.error.text()
    window.unlock("Velvet-Harbor-Quartz-Lantern7")
    wait_until(lambda: window.unlocked)
    assert [e.title for e in window.vault.entries] == ["GitHub"]
    window.lock()

    # recovery key flow sets a new password
    key = dlg.recovery_key
    from pwman.ui.vault_dialogs import RecoverAccessDialog
    rec = RecoverAccessDialog(window.config.effective_vault_path, window)
    rec.show()
    rec.key_edit.setText(key.lower())
    rec.next_btn.click()
    wait_until(lambda: rec.stack.currentIndex() == 1)
    rec.fields.pw.setText("Another-Strong-Passphrase-99")
    rec.fields.confirm.setText("Another-Strong-Passphrase-99")
    rec.set_btn.click()
    wait_until(lambda: rec.result() == QDialog.Accepted)
    Vault.unlock(window.config.effective_vault_path, "Another-Strong-Passphrase-99")


def test_auto_lock(window):
    create_vault(window)
    window.activity.start(1)
    window.activity._timer.setInterval(100)
    wait_until(lambda: not window.unlocked, timeout=5)
    assert "inactivity" in window.unlock_page.subtitle.text()


def test_lock_closes_open_dialogs(window):
    from pwman.ui.entry_dialog import EntryDialog

    create_vault(window)
    dlg = EntryDialog(window.config, None, 365, window._reuse_lookup, window)
    dlg.show()
    window.lock()
    assert not dlg.isVisible()


def test_entry_dialog_totp_and_generator(window):
    from pwman.ui.entry_dialog import EntryDialog

    create_vault(window)
    dlg = EntryDialog(window.config, None, 365, window._reuse_lookup, window)
    dlg.show()
    dlg.totp_edit.setText("otpauth://totp/ACME:alice?secret=JBSWY3DPEHPK3PXP&issuer=ACME")
    assert dlg.title_edit.text() == "ACME" and dlg.username_edit.text() == "alice"
    assert dlg.save_btn.isEnabled()
    dlg.totp_edit.setText("not valid!")
    assert not dlg.save_btn.isEnabled()
    dlg.totp_edit.setText("JBSW Y3DP EHPK 3PXP")
    dlg.password_edit.setText("x7#Kp9!qLm2@")
    dlg._save()
    assert dlg.result() == QDialog.Accepted
    entry = dlg.build_entry()
    assert entry.title == "ACME" and entry.totp.secret == "JBSWY3DPEHPK3PXP"
    assert entry.password == "x7#Kp9!qLm2@" and entry.password_history == []


def test_qr_decoding(app):
    zxingcpp = pytest.importorskip("zxingcpp")
    from pwman.ui.services import decode_qr_codes

    uri = "otpauth://totp/Test:me?secret=JBSWY3DPEHPK3PXP&issuer=Test"
    img = zxingcpp.create_barcode(uri, zxingcpp.BarcodeFormat.QRCode).to_image(scale=6)
    raw = bytes(memoryview(img))
    h, w = memoryview(img).shape
    qimg = QImage(raw, w, h, w, QImage.Format_Grayscale8).copy()
    # put it on a larger, odd-width canvas so row padding is exercised
    canvas = QImage(w + 101, h + 50, QImage.Format_RGB32)
    canvas.fill(Qt.white)
    from PySide6.QtGui import QPainter
    p = QPainter(canvas)
    p.drawImage(37, 20, qimg)
    p.end()
    assert decode_qr_codes(canvas) == [uri]
    blank = QImage(200, 200, QImage.Format_RGB32)
    blank.fill(Qt.white)
    assert decode_qr_codes(blank) == []


def test_generator_dialog_respects_options(window):
    from pwman.ui.generator_dialog import GeneratorDialog

    dlg = GeneratorDialog(window.config, use_button=True, parent=window)
    panel = dlg.panel
    panel.len_spin.setValue(32)
    panel.class_widgets["symbols"][0].setChecked(False)
    panel.class_widgets["digits"][1].setValue(5)
    value = dlg.value()
    assert len(value) == 32 and value.isalnum() and sum(c.isdigit() for c in value) >= 5
    panel.class_widgets["digits"][1].setValue(40)  # impossible
    assert not panel.error.isHidden() and dlg.value() == ""
    assert window.config.generator["length"] == 32
