"""Regenerate packaging/pwman.ico from the icon drawn in pwman/ui/app_icon.py.

Usage:  python packaging/make_icon.py      (needs Pillow + PySide6)
"""

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from pwman.ui.app_icon import render  # noqa: E402

app = QGuiApplication([])
images = []
for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    render(size).save(buf, "PNG")
    images.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA"))

out = ROOT / "packaging" / "pwman.ico"
images[-1].save(out, format="ICO", sizes=[im.size for im in images], append_images=images[:-1])
images[-1].save(ROOT / "packaging" / "pwman.png")
print(f"wrote {out}")
