"""Cryptographic primitives.

* Key derivation: Argon2id (memory-hard, resists GPU cracking).
* Encryption: AES-256-GCM (authenticated - any tampering is detected).
* Randomness: the operating system CSPRNG via :mod:`secrets`.
"""

from __future__ import annotations

import base64
import secrets
import unicodedata
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_LEN = 32  # 256-bit keys
NONCE_LEN = 12  # 96-bit GCM nonces
SALT_LEN = 16

# Crockford base32: no I, L, O or U, so keys are easy to read and type.
_RECOVERY_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_RECOVERY_CHARS = 32  # 32 chars * 5 bits = 160 bits of entropy
_RECOVERY_GROUP = 4


class DecryptionError(Exception):
    """Wrong key, or the data has been modified/corrupted."""


@dataclass(frozen=True)
class KdfParams:
    """Argon2id cost parameters.

    Defaults: 256 MiB of memory, 4 passes, 4 lanes - roughly 0.3-1 s per unlock on a
    typical PC, and very expensive to brute-force on GPUs.
    """

    time_cost: int = 4
    memory_cost: int = 256 * 1024  # KiB
    parallelism: int = 4

    def to_dict(self) -> dict:
        return {
            "name": "argon2id",
            "time_cost": self.time_cost,
            "memory_cost": self.memory_cost,
            "parallelism": self.parallelism,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KdfParams":
        if data.get("name") != "argon2id":
            raise ValueError(f"Unsupported key derivation function: {data.get('name')!r}")
        params = cls(
            time_cost=int(data["time_cost"]),
            memory_cost=int(data["memory_cost"]),
            parallelism=int(data["parallelism"]),
        )
        # Refuse absurd values so a crafted file cannot hang or exhaust the machine.
        if not (1 <= params.time_cost <= 64):
            raise ValueError("Invalid Argon2 time cost")
        if not (8 * params.parallelism <= params.memory_cost <= 4 * 1024 * 1024):
            raise ValueError("Invalid Argon2 memory cost")
        if not (1 <= params.parallelism <= 64):
            raise ValueError("Invalid Argon2 parallelism")
        return params


def normalize_secret(secret: str) -> bytes:
    """NFC-normalise so the same password typed via different input methods matches."""
    return unicodedata.normalize("NFC", secret).encode("utf-8")


def derive_key(secret: str, salt: bytes, params: KdfParams) -> bytes:
    """Derive a 256-bit key-encryption key from a password or recovery key."""
    return hash_secret_raw(
        secret=normalize_secret(secret),
        salt=salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_cost,
        parallelism=params.parallelism,
        hash_len=KEY_LEN,
        type=Type.ID,
    )


def random_bytes(n: int) -> bytes:
    return secrets.token_bytes(n)


def encrypt(key: bytes, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    """Encrypt with AES-256-GCM. Returns ``(nonce, ciphertext_with_tag)``."""
    nonce = random_bytes(NONCE_LEN)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except (InvalidTag, ValueError) as exc:
        raise DecryptionError("Decryption failed") from exc


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


# --------------------------------------------------------------------------- recovery key


def generate_recovery_key() -> str:
    """Return a new random recovery key like ``ABCD-EFGH-...`` (8 groups of 4)."""
    chars = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_CHARS))
    return format_recovery_key(chars)


def format_recovery_key(chars: str) -> str:
    return "-".join(chars[i : i + _RECOVERY_GROUP] for i in range(0, len(chars), _RECOVERY_GROUP))


def normalize_recovery_key(text: str) -> str:
    """Canonicalise user input: ignore case, spaces and dashes; fix look-alike letters.

    Raises ``ValueError`` if the result cannot be a valid recovery key.
    """
    cleaned = "".join(ch for ch in text.upper() if not ch.isspace() and ch not in "-_")
    cleaned = cleaned.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    if len(cleaned) != _RECOVERY_CHARS:
        raise ValueError(
            f"A recovery key has {_RECOVERY_CHARS} characters (you entered {len(cleaned)})."
        )
    bad = sorted({ch for ch in cleaned if ch not in _RECOVERY_ALPHABET})
    if bad:
        raise ValueError(f"Invalid character(s) in recovery key: {' '.join(bad)}")
    return format_recovery_key(cleaned)
