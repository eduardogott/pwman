"""Time-based one-time passwords (RFC 6238), as used by Google Authenticator & co.

Accepts a raw base32 secret, an ``otpauth://totp/...`` URI, or a Google
Authenticator export (``otpauth-migration://offline?data=...``).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

from .models import TotpConfig

ALGORITHMS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}
_B32_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def normalize_secret(secret: str) -> str:
    """Upper-case, strip spaces/dashes/padding and validate a base32 secret."""
    cleaned = "".join(ch for ch in secret.upper() if not ch.isspace() and ch not in "-=")
    if not cleaned:
        raise ValueError("The 2FA secret is empty.")
    bad = sorted(set(cleaned) - _B32_CHARS)
    if bad:
        raise ValueError(
            "The 2FA secret contains characters that are not valid base32: " + " ".join(bad)
        )
    decoded = _decode(cleaned)
    if len(decoded) < 5:
        raise ValueError("The 2FA secret is too short.")
    return cleaned


def _decode(secret: str) -> bytes:
    padded = secret + "=" * (-len(secret) % 8)
    try:
        return base64.b32decode(padded, casefold=True)
    except binascii.Error as exc:
        raise ValueError("The 2FA secret is not valid base32.") from exc


def generate(config: TotpConfig, at: float | None = None) -> str:
    """Return the current code for ``config`` (or the code at unix time ``at``)."""
    at = time.time() if at is None else at
    counter = int(at // config.period)
    digest_mod = ALGORITHMS.get(config.algorithm.upper())
    if digest_mod is None:
        raise ValueError(f"Unsupported TOTP algorithm: {config.algorithm}")
    mac = hmac.new(_decode(config.secret), struct.pack(">Q", counter), digest_mod).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** config.digits)).zfill(config.digits)


def seconds_remaining(config: TotpConfig, at: float | None = None) -> float:
    at = time.time() if at is None else at
    return config.period - (at % config.period)


def format_code(code: str) -> str:
    """'123456' -> '123 456' for readability."""
    mid = len(code) // 2
    return f"{code[:mid]} {code[mid:]}"


def _validate(config: TotpConfig) -> TotpConfig:
    config.secret = normalize_secret(config.secret)
    config.algorithm = config.algorithm.upper()
    if config.algorithm not in ALGORITHMS:
        raise ValueError(f"Unsupported algorithm {config.algorithm} (use SHA1, SHA256 or SHA512).")
    if config.digits not in (6, 7, 8):
        raise ValueError("2FA codes must have 6, 7 or 8 digits.")
    if not (5 <= config.period <= 300):
        raise ValueError("The 2FA period must be between 5 and 300 seconds.")
    return config


def parse_otpauth_uri(uri: str) -> TotpConfig:
    parsed = urlparse(uri.strip())
    if parsed.scheme.lower() != "otpauth":
        raise ValueError("Not an otpauth:// link.")
    if parsed.netloc.lower() != "totp":
        raise ValueError("Only time-based (TOTP) codes are supported, not counter-based (HOTP).")
    params = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items()}
    if "secret" not in params:
        raise ValueError("The otpauth link has no secret.")
    label = unquote(parsed.path.lstrip("/"))
    issuer, account = "", label
    if ":" in label:
        issuer, account = (part.strip() for part in label.split(":", 1))
    issuer = params.get("issuer", issuer)
    try:
        digits = int(params.get("digits", 6))
        period = int(params.get("period", 30))
    except ValueError as exc:
        raise ValueError("The otpauth link has invalid digits/period values.") from exc
    return _validate(TotpConfig(
        secret=params["secret"],
        algorithm=params.get("algorithm", "SHA1"),
        digits=digits,
        period=period,
        issuer=issuer,
        account=account,
    ))


def to_otpauth_uri(config: TotpConfig, fallback_label: str = "") -> str:
    account = config.account or fallback_label or "account"
    label = f"{config.issuer}:{account}" if config.issuer else account
    uri = (
        f"otpauth://totp/{quote(label)}?secret={config.secret}"
        f"&algorithm={config.algorithm}&digits={config.digits}&period={config.period}"
    )
    if config.issuer:
        uri += f"&issuer={quote(config.issuer)}"
    return uri


# --------------------------------------------------------------------------- Google Authenticator export


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("Truncated data")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("Varint too long")


def _iter_fields(data: bytes):
    """Minimal protobuf reader yielding (field_number, value) pairs."""
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        field_no, wire = tag >> 3, tag & 7
        if wire == 0:
            value, pos = _read_varint(data, pos)
        elif wire == 2:
            length, pos = _read_varint(data, pos)
            value, pos = data[pos : pos + length], pos + length
        elif wire == 1:
            value, pos = data[pos : pos + 8], pos + 8
        elif wire == 5:
            value, pos = data[pos : pos + 4], pos + 4
        else:
            raise ValueError("Unsupported protobuf wire type")
        yield field_no, value


def parse_migration_uri(uri: str) -> list[TotpConfig]:
    """Decode a Google Authenticator 'Transfer accounts' QR code."""
    parsed = urlparse(uri.strip())
    if parsed.scheme.lower() != "otpauth-migration":
        raise ValueError("Not a Google Authenticator export link.")
    data_param = parse_qs(parsed.query).get("data")
    if not data_param:
        raise ValueError("The export link has no data.")
    raw = base64.b64decode(data_param[0] + "=" * (-len(data_param[0]) % 4))
    algos = {0: "SHA1", 1: "SHA1", 2: "SHA256", 3: "SHA512"}
    digits_map = {0: 6, 1: 6, 2: 8}
    configs: list[TotpConfig] = []
    for field_no, value in _iter_fields(raw):
        if field_no != 1:
            continue
        info: dict = {}
        for f, v in _iter_fields(value):
            info[f] = v
        if info.get(6, 2) != 2:  # 1 = HOTP, 2 = TOTP
            continue
        secret = base64.b32encode(info.get(1, b"")).decode().rstrip("=")
        name = info.get(2, b"").decode("utf-8", "replace")
        issuer = info.get(3, b"").decode("utf-8", "replace")
        if ":" in name and not issuer:
            issuer, name = (part.strip() for part in name.split(":", 1))
        elif issuer and name.startswith(issuer + ":"):
            name = name[len(issuer) + 1 :].strip()
        configs.append(_validate(TotpConfig(
            secret=secret,
            algorithm=algos.get(info.get(4, 1), "SHA1"),
            digits=digits_map.get(info.get(5, 1), 6),
            period=30,
            issuer=issuer,
            account=name,
        )))
    if not configs:
        raise ValueError("The export contains no time-based (TOTP) accounts.")
    return configs


def parse_any(text: str) -> list[TotpConfig]:
    """Parse whatever the user pasted or a QR code contained."""
    text = text.strip()
    lowered = text.lower()
    if lowered.startswith("otpauth-migration://"):
        return parse_migration_uri(text)
    if lowered.startswith("otpauth://"):
        return [parse_otpauth_uri(text)]
    return [_validate(TotpConfig(secret=text))]
