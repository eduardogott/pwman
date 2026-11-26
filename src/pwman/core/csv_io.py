"""Import from / export to CSV files produced by browsers and other password managers.

Recognises the column names used by Chrome, Edge, Firefox, Brave, Bitwarden,
LastPass, 1Password, KeePass/KeePassXC, Proton Pass, Dashlane and generic files.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import totp
from .models import Entry, now_iso

COLUMN_ALIASES = {
    "title": ["title", "name", "account", "website name", "item name", "entry"],
    "url": ["url", "login_uri", "login uri", "website", "web site", "uri", "urls", "login url",
            "hostname", "origin"],
    "username": ["username", "login_username", "login username", "user name", "login", "email",
                 "user", "e-mail", "username/email"],
    "password": ["password", "login_password", "login password", "pass"],
    "notes": ["notes", "note", "extra", "comments", "comment"],
    "totp": ["totp", "login_totp", "otpauth", "otp", "2fa", "one-time password", "otp secret",
             "otpurl", "otp url", "otp_url"],
    "favorite": ["favorite", "favourite", "fav"],
    "password_changed": ["timepasswordchanged", "password changed", "last modified", "modified",
                         "lastmodified", "modifytime"],
    "created": ["timecreated", "created", "creation time", "createtime"],
}


class ImportResult:
    def __init__(self) -> None:
        self.entries: list[Entry] = []
        self.skipped = 0
        self.warnings: list[str] = []


def _map_columns(header: list[str]) -> dict[str, int]:
    normalized = [h.strip().lower().lstrip("﻿") for h in header]
    mapping: dict[str, int] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[field] = normalized.index(alias)
                break
    return mapping


def _parse_time(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if value.isdigit():  # Firefox: ms since epoch; others: seconds
        num = int(value)
        seconds = num / 1000 if num > 10**11 else num
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=0).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
        except ValueError:
            continue
    return None


def _title_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.hostname or url
    return host[4:] if host.startswith("www.") else host


def parse_csv_text(text: str) -> ImportResult:
    result = ImportResult()
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        result.warnings.append("The file is empty.")
        return result
    mapping = _map_columns(rows[0])
    if "password" not in mapping:
        raise ValueError(
            "Couldn't find a 'password' column. Supported exports: Chrome, Edge, Firefox, "
            "Bitwarden, LastPass, 1Password, KeePass(XC), Proton Pass, Dashlane."
        )

    def cell(row: list[str], field: str) -> str:
        idx = mapping.get(field)
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    for line_no, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        password = cell(row, "password")
        username = cell(row, "username")
        url = cell(row, "url")
        title = cell(row, "title") or _title_from_url(url) or username
        if not (password or username or url):
            result.skipped += 1
            continue
        changed = _parse_time(cell(row, "password_changed")) or now_iso()
        created = _parse_time(cell(row, "created")) or changed
        entry = Entry(
            title=title or f"Imported entry {line_no}",
            username=username,
            password=password,
            url=url,
            notes=cell(row, "notes"),
            favorite=cell(row, "favorite").lower() in {"1", "true", "yes", "x", "*"},
            created_at=created,
            password_changed_at=changed,
        )
        secret = cell(row, "totp")
        if secret:
            try:
                entry.totp = totp.parse_any(secret)[0]
            except ValueError as exc:
                result.warnings.append(f"Line {line_no} ({entry.title}): 2FA not imported - {exc}")
        result.entries.append(entry)
    return result


def parse_csv_file(path: Path | str) -> ImportResult:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return parse_csv_text(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    raise ValueError("Couldn't read the file's text encoding.")


EXPORT_COLUMNS = ["title", "username", "password", "url", "notes", "totp", "favorite",
                  "created", "password_changed"]


def export_csv_text(entries: list[Entry]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for e in entries:
        writer.writerow([
            e.title, e.username, e.password, e.url, e.notes,
            totp.to_otpauth_uri(e.totp, e.username or e.title) if e.totp else "",
            "1" if e.favorite else "", e.created_at, e.password_changed_at,
        ])
    return buf.getvalue()
