# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build definition.  Run from the repository root:
#     pyinstaller --noconfirm --clean packaging/pwman.spec
import sys
import tempfile
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is provided by PyInstaller)
sys.path.insert(0, str(ROOT / "src"))
from pwman import __version__  # noqa: E402

# ---------------------------------------------------------------- Windows file properties
version_file = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
        VSVersionInfo,
    )

    nums = tuple(int(x) for x in __version__.split(".")[:3]) + (0,)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "PwMan"),
                StringStruct("FileDescription", "PwMan offline password manager"),
                StringStruct("FileVersion", __version__),
                StringStruct("InternalName", "PwMan"),
                StringStruct("OriginalFilename", "PwMan.exe"),
                StringStruct("ProductName", "PwMan"),
                StringStruct("ProductVersion", __version__),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
    version_file = Path(tempfile.gettempdir()) / "pwman_version_info.txt"
    version_file.write_text(str(version_info), encoding="utf-8")

# ---------------------------------------------------------------- build
a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src" / "pwman" / "assets" / "eff_large_wordlist.txt"), "pwman/assets")],
    hiddenimports=["pwman.assets", "PySide6.QtSvg"],
    excludes=[
        "tkinter", "unittest", "pydoc", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.QtQuickWidgets", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSql",
        "PySide6.QtTest", "PySide6.QtDBus", "PySide6.QtDesigner", "PySide6.QtHelp",
        "PySide6.QtPrintSupport", "PySide6.QtUiTools", "PySide6.QtXml", "PySide6.QtConcurrent",
    ],
    noarchive=False,
)
# The UI is English-only and installs no QTranslator, so Qt's own translations are unused.
# (Linux wheels keep them in PySide6/Qt/translations, Windows wheels in PySide6/translations.)
a.datas = [d for d in a.datas
           if not d[0].replace("\\", "/").startswith(("PySide6/Qt/translations/", "PySide6/translations/"))]

pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PwMan",
    console=False,
    icon=str(ROOT / "packaging" / "pwman.ico"),
    version=str(version_file) if version_file else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PwMan", upx=False)  # noqa: F821
