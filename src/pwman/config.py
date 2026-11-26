"""Non-secret application preferences (stored unencrypted, outside the vault).

Only things needed *before* unlocking live here: which vault to open, the
theme, window size and the generator's last-used options. Nothing in this
file is sensitive.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import APP_NAME


def data_dir() -> Path:
    """Per-user folder for the vault and backups (e.g. %APPDATA%\\PwMan on Windows)."""
    override = os.environ.get("PWMAN_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME.lower()


def default_vault_path() -> Path:
    return data_dir() / "vault.pwm"


def config_path() -> Path:
    return data_dir() / "settings.json"


@dataclass
class AppConfig:
    vault_path: str = ""
    recent_vaults: list[str] = field(default_factory=list)
    theme: str = "system"  # system | light | dark
    window_geometry: str = ""  # hex-encoded QByteArray
    generator: dict = field(default_factory=dict)
    passphrase: dict = field(default_factory=dict)
    generator_mode: str = "password"  # password | passphrase

    @property
    def effective_vault_path(self) -> Path:
        return Path(self.vault_path) if self.vault_path else default_vault_path()

    def remember_vault(self, path: Path | str) -> None:
        path = str(Path(path))
        self.vault_path = path
        self.recent_vaults = [path] + [p for p in self.recent_vaults if p != path][:7]

    @classmethod
    def load(cls) -> "AppConfig":
        try:
            data = json.loads(config_path().read_text("utf-8"))
        except (OSError, ValueError):
            return cls()
        names = {f.name for f in fields(cls)}
        try:
            return cls(**{k: v for k, v in data.items() if k in names})
        except TypeError:
            return cls()

    def save(self) -> None:
        path = config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2), "utf-8")
            os.replace(tmp, path)
        except OSError:
            pass  # preferences are best-effort
