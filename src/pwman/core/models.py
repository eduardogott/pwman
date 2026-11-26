"""Data model for vault entries and vault-level settings."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone

PASSWORD_HISTORY_LIMIT = 20


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def age_in_days(value: str | None, now: datetime | None = None) -> int | None:
    dt = parse_iso(value)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, (now - dt).days)


def _split_known(cls, data: dict) -> tuple[dict, dict]:
    """Separate keys the dataclass knows from unknown ones (kept for forward compatibility)."""
    names = {f.name for f in fields(cls)} - {"extra"}
    known = {k: v for k, v in data.items() if k in names}
    extra = {k: v for k, v in data.items() if k not in names}
    return known, extra


@dataclass
class TotpConfig:
    secret: str  # base32, normalised (upper case, no spaces/padding)
    algorithm: str = "SHA1"
    digits: int = 6
    period: int = 30
    issuer: str = ""
    account: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TotpConfig":
        known, _ = _split_known(cls, data)
        return cls(**known)


@dataclass
class PasswordHistoryItem:
    password: str
    changed_at: str  # when this password stopped being the current one

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PasswordHistoryItem":
        return cls(password=data.get("password", ""), changed_at=data.get("changed_at", ""))


@dataclass
class Entry:
    title: str
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""
    totp: TotpConfig | None = None
    favorite: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    password_changed_at: str = field(default_factory=now_iso)
    password_history: list[PasswordHistoryItem] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def set_password(self, new_password: str) -> None:
        """Change the password, archiving the old one and resetting its age."""
        if new_password == self.password:
            return
        if self.password:
            self.password_history.insert(0, PasswordHistoryItem(self.password, now_iso()))
            del self.password_history[PASSWORD_HISTORY_LIMIT:]
        self.password = new_password
        self.password_changed_at = now_iso()

    def touch(self) -> None:
        self.updated_at = now_iso()

    def password_age_days(self, now: datetime | None = None) -> int | None:
        return age_in_days(self.password_changed_at, now)

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "title": self.title,
            "username": self.username,
            "password": self.password,
            "url": self.url,
            "notes": self.notes,
            "totp": self.totp.to_dict() if self.totp else None,
            "favorite": self.favorite,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "password_changed_at": self.password_changed_at,
            "password_history": [h.to_dict() for h in self.password_history],
        }
        return {**self.extra, **data}

    @classmethod
    def from_dict(cls, data: dict) -> "Entry":
        known, extra = _split_known(cls, data)
        totp = known.pop("totp", None)
        history = known.pop("password_history", []) or []
        entry = cls(**known)
        entry.totp = TotpConfig.from_dict(totp) if totp else None
        entry.password_history = [PasswordHistoryItem.from_dict(h) for h in history]
        entry.extra = extra
        return entry


@dataclass
class VaultSettings:
    auto_lock_minutes: int = 5  # 0 = never
    lock_on_minimize: bool = False
    lock_on_system_lock: bool = True  # Windows: lock when the computer is locked
    clipboard_clear_seconds: int = 30  # 0 = never
    password_max_age_days: int = 365
    screen_capture_protection: bool = False  # Windows: hide window from screenshots
    backup_count: int = 10
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        extra = data.pop("extra")
        return {**extra, **data}

    @classmethod
    def from_dict(cls, data: dict) -> "VaultSettings":
        known, extra = _split_known(cls, data or {})
        settings = cls(**known)
        settings.extra = extra
        return settings
