import base64

import pytest

from pwman.core import totp
from pwman.core.models import TotpConfig

# RFC 6238 appendix B test vectors
RFC_SECRETS = {
    "SHA1": base64.b32encode(b"12345678901234567890").decode(),
    "SHA256": base64.b32encode(b"12345678901234567890123456789012").decode(),
    "SHA512": base64.b32encode(b"1234567890123456789012345678901234567890123456789012345678901234").decode(),
}
RFC_VECTORS = [
    (59, "94287082", "46119246", "90693936"),
    (1111111109, "07081804", "68084774", "25091201"),
    (1111111111, "14050471", "67062674", "99943326"),
    (1234567890, "89005924", "91819424", "93441116"),
    (2000000000, "69279037", "90698825", "38618901"),
    (20000000000, "65353130", "77737706", "47863826"),
]


@pytest.mark.parametrize("t,sha1,sha256,sha512", RFC_VECTORS)
def test_rfc6238_vectors(t, sha1, sha256, sha512):
    for algo, expected in (("SHA1", sha1), ("SHA256", sha256), ("SHA512", sha512)):
        cfg = TotpConfig(secret=RFC_SECRETS[algo].rstrip("="), algorithm=algo, digits=8)
        assert totp.generate(cfg, at=t) == expected


def test_parse_otpauth_uri():
    cfg = totp.parse_otpauth_uri(
        "otpauth://totp/ACME%20Co:john.doe@email.com?secret=HXDMVJECJJWSRB3HWIZR4IFUGFTMXBOZ"
        "&issuer=ACME%20Co&algorithm=SHA1&digits=6&period=30"
    )
    assert cfg.issuer == "ACME Co" and cfg.account == "john.doe@email.com"
    assert cfg.secret == "HXDMVJECJJWSRB3HWIZR4IFUGFTMXBOZ" and cfg.digits == 6
    again = totp.parse_otpauth_uri(totp.to_otpauth_uri(cfg))
    assert again == cfg


def test_parse_raw_secret_with_spaces():
    [cfg] = totp.parse_any("jbsw y3dp ehpk 3pxp")
    assert cfg.secret == "JBSWY3DPEHPK3PXP"


@pytest.mark.parametrize("bad", ["", "not base32!", "otpauth://hotp/x?secret=JBSWY3DPEHPK3PXP",
                                 "otpauth://totp/x?digits=6", "AB"])
def test_invalid_input(bad):
    with pytest.raises(ValueError):
        totp.parse_any(bad)


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(no, value):
    if isinstance(value, int):
        return _varint(no << 3) + _varint(value)
    return _varint(no << 3 | 2) + _varint(len(value)) + value


def test_google_authenticator_migration():
    otp1 = (_field(1, b"12345678901234567890") + _field(2, b"alice@example.com")
            + _field(3, b"Example") + _field(4, 1) + _field(5, 1) + _field(6, 2))
    otp2 = _field(1, b"abcdefghij") + _field(2, b"GitHub:bob") + _field(6, 2)
    hotp = _field(1, b"zzzzzzzzzz") + _field(2, b"counter") + _field(6, 1)
    payload = _field(1, otp1) + _field(1, otp2) + _field(1, hotp) + _field(2, 1)
    uri = "otpauth-migration://offline?data=" + base64.b64encode(payload).decode()
    configs = totp.parse_any(uri)
    assert [(c.issuer, c.account) for c in configs] == [("Example", "alice@example.com"),
                                                        ("GitHub", "bob")]
    assert totp.generate(configs[0], at=59)[-6:] == "287082"


def test_seconds_remaining_and_format():
    cfg = TotpConfig(secret="JBSWY3DPEHPK3PXP")
    assert totp.seconds_remaining(cfg, at=60) == 30
    assert totp.seconds_remaining(cfg, at=89.5) == 0.5
    assert totp.format_code("123456") == "123 456"
