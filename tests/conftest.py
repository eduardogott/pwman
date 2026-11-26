import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pwman.core.crypto import KdfParams  # noqa: E402

# Cheap Argon2 parameters so the test-suite runs fast. Real vaults use the defaults.
FAST_KDF = KdfParams(time_cost=1, memory_cost=1024, parallelism=1)


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PWMAN_HOME", str(tmp_path / "home"))
    return tmp_path / "home"
