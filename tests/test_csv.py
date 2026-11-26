import pytest

from pwman.core import csv_io

CHROME = """name,url,username,password,note
github.com,https://github.com/login,alice,gh-pass,
,https://www.example.org/,bob,ex-pass,some note
"""

FIREFOX = """"url","username","password","httpRealm","formActionOrigin","guid","timeCreated","timeLastUsed","timePasswordChanged"
"https://accounts.google.com","carol@gmail.com","g-pass",,"https://accounts.google.com","{x}","1600000000000","1600000000000","1650000000000"
"""

BITWARDEN = """folder,favorite,type,name,notes,fields,reprompt,login_uri,login_username,login_password,login_totp
,1,login,Bank,,,0,https://bank.example,dave,b-pass,otpauth://totp/Bank:dave?secret=JBSWY3DPEHPK3PXP&issuer=Bank
,,login,Broken2FA,,,0,https://x.example,erin,x-pass,not-a-secret!!
"""

KEEPASS_SEMICOLON = """Title;Username;Password;URL;Notes
Router;admin;r-pass;http://192.168.0.1;
"""


def test_chrome():
    res = csv_io.parse_csv_text(CHROME)
    assert [(e.title, e.username, e.password) for e in res.entries] == [
        ("github.com", "alice", "gh-pass"), ("example.org", "bob", "ex-pass")]
    assert res.entries[1].notes == "some note"


def test_firefox_timestamps():
    [e] = csv_io.parse_csv_text(FIREFOX).entries
    assert e.title == "accounts.google.com" and e.password == "g-pass"
    assert e.password_changed_at.startswith("2022-04-15")
    assert e.created_at.startswith("2020-09-13")


def test_bitwarden_with_totp_and_warning():
    res = csv_io.parse_csv_text(BITWARDEN)
    bank, broken = res.entries
    assert bank.favorite and bank.totp.secret == "JBSWY3DPEHPK3PXP" and bank.totp.issuer == "Bank"
    assert broken.totp is None and len(res.warnings) == 1


def test_semicolon_delimiter():
    [e] = csv_io.parse_csv_text(KEEPASS_SEMICOLON).entries
    assert (e.title, e.username, e.password, e.url) == ("Router", "admin", "r-pass", "http://192.168.0.1")


def test_missing_password_column():
    with pytest.raises(ValueError):
        csv_io.parse_csv_text("a,b\n1,2\n")


def test_export_import_roundtrip():
    entries = csv_io.parse_csv_text(BITWARDEN).entries
    again = csv_io.parse_csv_text(csv_io.export_csv_text(entries)).entries
    assert [(e.title, e.password, e.favorite) for e in again] == [
        (e.title, e.password, e.favorite) for e in entries]
    assert again[0].totp == entries[0].totp
