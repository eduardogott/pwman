"""Encrypted vault file.

Layout (JSON, every binary value base64-encoded)::

    {
      "format": "pwman-vault", "version": 1,
      "master":   {"kdf": {...}, "salt": .., "nonce": .., "wrapped_key": ..},
      "recovery": {"kdf": {...}, "salt": .., "nonce": .., "wrapped_key": ..},
      "payload":  {"nonce": .., "ciphertext": ..}
    }

A random 256-bit *vault key* encrypts the payload (entries + settings) with
AES-256-GCM. The vault key itself is stored twice, each copy encrypted
("wrapped") with a key derived via Argon2id from either the master password or
the recovery key. Either secret therefore unlocks the vault, and changing the
master password only re-wraps the vault key. Everything except the payload is
used as additional authenticated data, so tampering with any part of the file
is detected.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import crypto
from .crypto import KdfParams
from .models import Entry, VaultSettings

FORMAT_NAME = "pwman-vault"
FORMAT_VERSION = 1
FILE_SUFFIX = ".pwm"
SLOT_MASTER = "master"
SLOT_RECOVERY = "recovery"
DEFAULT_KDF = KdfParams()


class VaultError(Exception):
    """Base class for vault problems that should be shown to the user."""


class WrongSecretError(VaultError):
    """The master password or recovery key is incorrect."""


class CorruptVaultError(VaultError):
    """The file is not a valid vault, or has been damaged/tampered with."""


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _slot_aad(slot_name: str) -> bytes:
    return f"pwman:{slot_name}-key:v{FORMAT_VERSION}".encode()


def _wrap_key(vault_key: bytes, secret: str, slot_name: str, kdf: KdfParams) -> dict:
    salt = crypto.random_bytes(crypto.SALT_LEN)
    kek = crypto.derive_key(secret, salt, kdf)
    nonce, wrapped = crypto.encrypt(kek, vault_key, _slot_aad(slot_name))
    return {
        "kdf": kdf.to_dict(),
        "salt": crypto.b64e(salt),
        "nonce": crypto.b64e(nonce),
        "wrapped_key": crypto.b64e(wrapped),
    }


def _unwrap_key(slot: dict, secret: str, slot_name: str) -> bytes:
    try:
        kdf = KdfParams.from_dict(slot["kdf"])
        salt = crypto.b64d(slot["salt"])
        nonce = crypto.b64d(slot["nonce"])
        wrapped = crypto.b64d(slot["wrapped_key"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CorruptVaultError(f"The vault's {slot_name} key slot is damaged.") from exc
    kek = crypto.derive_key(secret, salt, kdf)
    try:
        key = crypto.decrypt(kek, nonce, wrapped, _slot_aad(slot_name))
    except crypto.DecryptionError as exc:
        raise WrongSecretError() from exc
    if len(key) != crypto.KEY_LEN:
        raise CorruptVaultError("The vault key has an invalid length.")
    return key


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via a temp file + rename so a crash never leaves a half-written vault."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # On Windows, antivirus/indexers can briefly hold the target file open.
            if attempt == 5:
                raise
            time.sleep(0.15 * (attempt + 1))


class Vault:
    """An unlocked vault. Holds the decrypted entries and the vault key in memory."""

    def __init__(self, path: Path, vault_key: bytes, header: dict,
                 entries: list[Entry], settings: VaultSettings):
        self.path = Path(path)
        self._key: bytes | None = vault_key
        self._header = header
        self.entries = entries
        self.settings = settings
        self._backed_up_this_session = False

    # ------------------------------------------------------------------ opening
    @staticmethod
    def exists(path: Path | str) -> bool:
        return Path(path).is_file()

    @classmethod
    def create(cls, path: Path | str, master_password: str,
               kdf: KdfParams | None = None) -> tuple["Vault", str]:
        """Create a new vault file. Returns the vault and its recovery key."""
        path = Path(path)
        if path.exists():
            raise VaultError(f"A file already exists at {path}")
        if not master_password:
            raise VaultError("The master password cannot be empty.")
        path.parent.mkdir(parents=True, exist_ok=True)
        kdf = kdf or DEFAULT_KDF
        vault_key = crypto.random_bytes(crypto.KEY_LEN)
        recovery_key = crypto.generate_recovery_key()
        header = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            SLOT_MASTER: _wrap_key(vault_key, master_password, SLOT_MASTER, kdf),
            SLOT_RECOVERY: _wrap_key(vault_key, recovery_key, SLOT_RECOVERY, kdf),
        }
        vault = cls(path, vault_key, header, [], VaultSettings())
        vault.save()
        return vault, recovery_key

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            raw = Path(path).read_bytes()
        except FileNotFoundError as exc:
            raise VaultError(f"Vault file not found: {path}") from exc
        try:
            doc = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CorruptVaultError("This file is not a PwMan vault (or it is damaged).") from exc
        if not isinstance(doc, dict) or doc.get("format") != FORMAT_NAME:
            raise CorruptVaultError("This file is not a PwMan vault.")
        version = doc.get("version")
        if not isinstance(version, int) or version < 1:
            raise CorruptVaultError("The vault has an invalid version number.")
        if version > FORMAT_VERSION:
            raise VaultError("This vault was created by a newer version of PwMan. Please update.")
        return doc

    @classmethod
    def _open(cls, path: Path | str, secret: str, slot_name: str) -> "Vault":
        path = Path(path)
        doc = cls._read(path)
        slot = doc.get(slot_name)
        if not isinstance(slot, dict):
            raise CorruptVaultError(f"The vault has no {slot_name} key slot.")
        key = _unwrap_key(slot, secret, slot_name)
        header = {k: v for k, v in doc.items() if k != "payload"}
        payload = cls._decrypt_payload(doc, key)
        try:
            entries = [Entry.from_dict(e) for e in payload.get("entries", [])]
            settings = VaultSettings.from_dict(payload.get("settings", {}))
        except (TypeError, ValueError, KeyError) as exc:
            raise CorruptVaultError("The vault contents could not be read.") from exc
        return cls(path, key, header, entries, settings)

    @staticmethod
    def _decrypt_payload(doc: dict, key: bytes) -> dict:
        header = {k: v for k, v in doc.items() if k != "payload"}
        try:
            payload = doc["payload"]
            nonce = crypto.b64d(payload["nonce"])
            ciphertext = crypto.b64d(payload["ciphertext"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptVaultError("The vault data section is damaged.") from exc
        try:
            plaintext = crypto.decrypt(key, nonce, ciphertext, _canonical(header))
        except crypto.DecryptionError as exc:
            raise CorruptVaultError(
                "The vault data failed its integrity check - the file is damaged or was "
                "modified. Try restoring a backup."
            ) from exc
        return json.loads(plaintext)

    @classmethod
    def unlock(cls, path: Path | str, master_password: str) -> "Vault":
        return cls._open(path, master_password, SLOT_MASTER)

    @classmethod
    def unlock_with_recovery_key(cls, path: Path | str, recovery_key: str) -> "Vault":
        try:
            normalized = crypto.normalize_recovery_key(recovery_key)
        except ValueError as exc:
            raise WrongSecretError(str(exc)) from exc
        return cls._open(path, normalized, SLOT_RECOVERY)

    # ------------------------------------------------------------------ state
    @property
    def is_locked(self) -> bool:
        return self._key is None

    def _require_key(self) -> bytes:
        if self._key is None:
            raise VaultError("The vault is locked.")
        return self._key

    def lock(self) -> None:
        """Forget the key and decrypted data."""
        self._key = None
        self.entries = []

    # ------------------------------------------------------------------ saving
    @property
    def backup_dir(self) -> Path:
        return self.path.parent / "backups"

    def _backup_existing(self) -> None:
        if self._backed_up_this_session or self.settings.backup_count <= 0:
            return
        if self.path.is_file():
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = self.backup_dir / f"{self.path.stem}-{stamp}{self.path.suffix or FILE_SUFFIX}"
            shutil.copy2(self.path, target)
            pattern = f"{glob.escape(self.path.stem)}-*{glob.escape(self.path.suffix or FILE_SUFFIX)}"
            backups = sorted(self.backup_dir.glob(pattern))
            for old in backups[: max(0, len(backups) - self.settings.backup_count)]:
                try:
                    old.unlink()
                except OSError:
                    pass
        self._backed_up_this_session = True

    def _serialize(self) -> bytes:
        key = self._require_key()
        payload = {
            "entries": [e.to_dict() for e in self.entries],
            "settings": self.settings.to_dict(),
        }
        plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        nonce, ciphertext = crypto.encrypt(key, plaintext, _canonical(self._header))
        doc = dict(self._header)
        doc["payload"] = {"nonce": crypto.b64e(nonce), "ciphertext": crypto.b64e(ciphertext)}
        return json.dumps(doc, indent=1).encode("ascii")

    def save(self) -> None:
        """Encrypt and write the vault, verifying the result before replacing the old file."""
        data = self._serialize()
        # Verify we can read back what we are about to write.
        check = self._decrypt_payload(json.loads(data), self._require_key())
        if len(check.get("entries", [])) != len(self.entries):
            raise VaultError("Internal error: vault verification failed; nothing was saved.")
        self._backup_existing()
        _atomic_write(self.path, data)

    def save_copy(self, target: Path | str) -> None:
        """Write an encrypted copy of the vault (same passwords) to another location."""
        Path(target).write_bytes(self._serialize())

    # ------------------------------------------------------------------ secrets
    def verify_master_password(self, password: str) -> bool:
        try:
            return _unwrap_key(self._header[SLOT_MASTER], password, SLOT_MASTER) == self._require_key()
        except WrongSecretError:
            return False

    def change_master_password(self, new_password: str) -> None:
        if not new_password:
            raise VaultError("The master password cannot be empty.")
        kdf = KdfParams.from_dict(self._header[SLOT_MASTER]["kdf"])
        self._header[SLOT_MASTER] = _wrap_key(self._require_key(), new_password, SLOT_MASTER, kdf)
        self.save()

    def regenerate_recovery_key(self) -> str:
        """Replace the recovery key. The old one stops working immediately."""
        kdf = KdfParams.from_dict(self._header[SLOT_RECOVERY]["kdf"])
        recovery_key = crypto.generate_recovery_key()
        self._header[SLOT_RECOVERY] = _wrap_key(self._require_key(), recovery_key, SLOT_RECOVERY, kdf)
        self.save()
        return recovery_key

    # ------------------------------------------------------------------ entries
    def get(self, entry_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    def add(self, entry: Entry) -> None:
        self.entries.append(entry)

    def remove(self, entry_id: str) -> None:
        self.entries = [e for e in self.entries if e.id != entry_id]
