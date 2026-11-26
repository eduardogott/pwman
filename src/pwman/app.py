"""Application entry point."""

from __future__ import annotations

import os
import sys
import traceback


def self_test(report_path: str | None) -> int:
    """Exercise every bundled component without touching the user's data.

    Used by the build pipeline to check that the frozen .exe works:
    ``PwMan.exe --self-test result.txt`` (exit code 0 = OK).
    """
    import tempfile
    from pathlib import Path

    lines: list[str] = []
    ok = True

    def check(name, fn):
        nonlocal ok
        try:
            detail = fn()
            lines.append(f"PASS {name}" + (f": {detail}" if detail else ""))
        except Exception:
            ok = False
            lines.append(f"FAIL {name}\n{traceback.format_exc()}")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PWMAN_HOME"] = tmp

        def vault_roundtrip():
            from .core.models import Entry
            from .core.vault import Vault
            vault, key = Vault.create(Path(tmp) / "t.pwm", "self-test password")
            vault.add(Entry(title="t", password="p"))
            vault.save()
            assert Vault.unlock(Path(tmp) / "t.pwm", "self-test password").entries[0].password == "p"
            assert Vault.unlock_with_recovery_key(Path(tmp) / "t.pwm", key).entries
            return "argon2id + aes-gcm"

        def totp_check():
            from .core import totp
            from .core.models import TotpConfig
            cfg = TotpConfig(secret="GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", digits=8)
            assert totp.generate(cfg, at=59) == "94287082"

        def generator_check():
            from .core import generator, strength
            pw = generator.generate_password(generator.GeneratorOptions())
            phrase = generator.generate_passphrase(generator.PassphraseOptions())
            return f"{strength.evaluate(pw).label}, {len(generator.wordlist())} words, {phrase.count('-') + 1}-word phrase"

        def gui_check():
            from PySide6.QtWidgets import QApplication
            from .config import AppConfig
            from .ui import theme
            from .ui.main_window import MainWindow
            app = QApplication.instance() or QApplication([])
            theme.apply(app, "dark")
            win = MainWindow(AppConfig.load())
            win.show()
            app.processEvents()
            win.close()
            return app.platformName()

        def qr_check():
            import zxingcpp
            from PySide6.QtGui import QImage
            from .ui.services import decode_qr_codes
            img = zxingcpp.create_barcode("otpauth://totp/x?secret=JBSWY3DPEHPK3PXP",
                                          zxingcpp.BarcodeFormat.QRCode).to_image(scale=5)
            h, w = memoryview(img).shape
            qimg = QImage(bytes(memoryview(img)), w, h, w, QImage.Format_Grayscale8).copy()
            assert decode_qr_codes(qimg) == ["otpauth://totp/x?secret=JBSWY3DPEHPK3PXP"]

        for name, fn in (("vault", vault_roundtrip), ("totp", totp_check),
                         ("generator", generator_check), ("gui", gui_check), ("qr", qr_check)):
            check(name, fn)

    text = "\n".join(lines) + f"\n{'OK' if ok else 'FAILED'}\n"
    if report_path:
        Path(report_path).write_text(text, "utf-8")
    elif sys.stdout:
        sys.stdout.write(text)
    return 0 if ok else 1


def main() -> int:
    if "--self-test" in sys.argv:
        idx = sys.argv.index("--self-test")
        return self_test(sys.argv[idx + 1] if len(sys.argv) > idx + 1 else None)

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME, __version__
    from .config import AppConfig
    from .ui import theme
    from .ui.app_icon import app_icon
    from .ui.main_window import MainWindow

    if sys.platform == "win32":
        # Own taskbar icon/grouping instead of python.exe's.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"PwMan.PwMan.{__version__}")
        except Exception:
            pass

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setWindowIcon(app_icon())

    config = AppConfig.load()
    theme.apply(app, config.theme)
    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
