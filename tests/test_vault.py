import json

import pytest

from pwman.core import crypto
from pwman.core.models import Entry, TotpConfig
from pwman.core.vault import CorruptVaultError, Vault, VaultError, WrongSecretError

from conftest import FAST_KDF


def make_vault(tmp_path, password="correct horse battery staple"):
    return Vault.create(tmp_path / "v.pwm", password, kdf=FAST_KDF)


def test_create_and_unlock_roundtrip(tmp_path):
    vault, recovery = make_vault(tmp_path)
    entry = Entry(title="GitHub", username="me", password="s3cret!", url="https://github.com",
                  totp=TotpConfig(secret="JBSWY3DPEHPK3PXP"))
    vault.add(entry)
    vault.settings.auto_lock_minutes = 9
    vault.save()

    reopened = Vault.unlock(tmp_path / "v.pwm", "correct horse battery staple")
    assert [e.title for e in reopened.entries] == ["GitHub"]
    got = reopened.entries[0]
    assert got.password == "s3cret!" and got.totp.secret == "JBSWY3DPEHPK3PXP"
    assert reopened.settings.auto_lock_minutes == 9


def test_file_contains_no_plaintext(tmp_path):
    vault, recovery = make_vault(tmp_path)
    vault.add(Entry(title="MyBank", username="alice@example.com", password="hunter2-unique"))
    vault.save()
    raw = (tmp_path / "v.pwm").read_text()
    for secret in ("MyBank", "alice@example.com", "hunter2-unique", recovery):
        assert secret not in raw


def test_wrong_password_rejected(tmp_path):
    make_vault(tmp_path)
    with pytest.raises(WrongSecretError):
        Vault.unlock(tmp_path / "v.pwm", "wrong")


def test_recovery_key_unlocks_and_allows_reset(tmp_path):
    vault, recovery = make_vault(tmp_path)
    vault.add(Entry(title="x", password="y"))
    vault.save()
    # user input is forgiving: lower case, spaces instead of dashes, O instead of 0
    sloppy = recovery.lower().replace("-", " ").replace("0", "o")
    recovered = Vault.unlock_with_recovery_key(tmp_path / "v.pwm", sloppy)
    assert recovered.entries[0].password == "y"
    recovered.change_master_password("brand new password")
    assert Vault.unlock(tmp_path / "v.pwm", "brand new password").entries[0].title == "x"
    with pytest.raises(WrongSecretError):
        Vault.unlock(tmp_path / "v.pwm", "correct horse battery staple")
    # recovery key still works after a password change
    Vault.unlock_with_recovery_key(tmp_path / "v.pwm", recovery)


def test_wrong_recovery_key(tmp_path):
    make_vault(tmp_path)
    with pytest.raises(WrongSecretError):
        Vault.unlock_with_recovery_key(tmp_path / "v.pwm", crypto.generate_recovery_key())
    with pytest.raises(WrongSecretError):
        Vault.unlock_with_recovery_key(tmp_path / "v.pwm", "too-short")


def test_regenerate_recovery_key_invalidates_old(tmp_path):
    vault, old = make_vault(tmp_path)
    new = vault.regenerate_recovery_key()
    assert new != old
    Vault.unlock_with_recovery_key(tmp_path / "v.pwm", new)
    with pytest.raises(WrongSecretError):
        Vault.unlock_with_recovery_key(tmp_path / "v.pwm", old)


def test_tampering_detected(tmp_path):
    vault, _ = make_vault(tmp_path)
    vault.add(Entry(title="x", password="y"))
    vault.save()
    path = tmp_path / "v.pwm"
    doc = json.loads(path.read_text())
    ct = bytearray(crypto.b64d(doc["payload"]["ciphertext"]))
    ct[5] ^= 0x01
    doc["payload"]["ciphertext"] = crypto.b64e(bytes(ct))
    path.write_text(json.dumps(doc))
    with pytest.raises(CorruptVaultError):
        Vault.unlock(path, "correct horse battery staple")


def test_header_tampering_detected(tmp_path):
    """Swapping key slots or editing the header must break the payload's integrity check."""
    make_vault(tmp_path)
    path = tmp_path / "v.pwm"
    doc = json.loads(path.read_text())
    doc["recovery"]["salt"] = crypto.b64e(b"\0" * 16)
    path.write_text(json.dumps(doc))
    with pytest.raises(CorruptVaultError):
        Vault.unlock(path, "correct horse battery staple")


def test_not_a_vault(tmp_path):
    path = tmp_path / "junk.pwm"
    path.write_text("hello")
    with pytest.raises(CorruptVaultError):
        Vault.unlock(path, "x")
    path.write_text(json.dumps({"format": "pwman-vault", "version": 99}))
    with pytest.raises(VaultError, match="newer version"):
        Vault.unlock(path, "x")


def test_malicious_kdf_params_rejected(tmp_path):
    make_vault(tmp_path)
    path = tmp_path / "v.pwm"
    doc = json.loads(path.read_text())
    doc["master"]["kdf"]["memory_cost"] = 1 << 40
    path.write_text(json.dumps(doc))
    with pytest.raises(CorruptVaultError):
        Vault.unlock(path, "correct horse battery staple")


def test_create_refuses_to_overwrite(tmp_path):
    make_vault(tmp_path)
    with pytest.raises(VaultError):
        make_vault(tmp_path)


def test_backups_rotate(tmp_path, monkeypatch):
    vault, _ = make_vault(tmp_path)
    vault.settings.backup_count = 3
    stamps = iter(f"2026010{i}-000000" for i in range(1, 9))

    class FakeNow:
        @staticmethod
        def now():
            class D:
                def strftime(self, _):
                    return next(stamps)
            return D()

    import pwman.core.vault as vault_mod
    monkeypatch.setattr(vault_mod, "datetime", FakeNow)
    for i in range(6):
        vault._backed_up_this_session = False  # simulate a new session each time
        vault.add(Entry(title=f"e{i}"))
        vault.save()
    backups = sorted(vault.backup_dir.iterdir())
    assert len(backups) == 3
    # every backup is a valid encrypted vault
    for b in backups:
        Vault.unlock(b, "correct horse battery staple")


def test_verify_master_password(tmp_path):
    vault, _ = make_vault(tmp_path)
    assert vault.verify_master_password("correct horse battery staple")
    assert not vault.verify_master_password("nope")


def test_lock_forgets_data(tmp_path):
    vault, _ = make_vault(tmp_path)
    vault.add(Entry(title="x"))
    vault.lock()
    assert vault.is_locked and vault.entries == []
    with pytest.raises(VaultError):
        vault.save()


def test_unknown_fields_preserved(tmp_path):
    vault, _ = make_vault(tmp_path)
    e = Entry.from_dict({"title": "t", "future_field": [1, 2]})
    vault.add(e)
    vault.save()
    again = Vault.unlock(tmp_path / "v.pwm", "correct horse battery staple")
    assert again.entries[0].to_dict()["future_field"] == [1, 2]


def test_password_history():
    e = Entry(title="t", password="one")
    e.set_password("two")
    e.set_password("two")  # unchanged -> no new history entry
    e.set_password("three")
    assert [h.password for h in e.password_history] == ["two", "one"]


def test_unicode_password_normalization(tmp_path):
    # "é" as one code point vs. "e" + combining accent must unlock the same vault
    Vault.create(tmp_path / "u.pwm", "café-päss", kdf=FAST_KDF)
    Vault.unlock(tmp_path / "u.pwm", "café-päss")
