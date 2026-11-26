"""Background tasks, secure clipboard, inactivity tracking and QR decoding."""

from __future__ import annotations

import threading
import time
from typing import Callable

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QImage

from . import platform


class Task(QObject):
    """Run ``fn`` on a worker thread; deliver the result on the GUI thread.

    Used for Argon2 key derivation so the window stays responsive.
    """

    _finished = Signal(bool, object)

    def __init__(self, parent: QObject, fn: Callable[[], object],
                 on_success: Callable[[object], None], on_error: Callable[[Exception], None]):
        super().__init__(parent)
        self._fn, self._ok, self._err = fn, on_success, on_error
        self._finished.connect(self._deliver)

    @classmethod
    def run(cls, parent, fn, on_success, on_error) -> "Task":
        task = cls(parent, fn, on_success, on_error)
        threading.Thread(target=task._work, daemon=True).start()
        return task

    def _work(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # delivered to the GUI as an error
            self._finished.emit(False, exc)
        else:
            self._finished.emit(True, result)

    @Slot(bool, object)
    def _deliver(self, ok: bool, value: object) -> None:
        try:
            (self._ok if ok else self._err)(value)
        finally:
            self.deleteLater()


class SecureClipboard(QObject):
    """Copies secrets, keeps them out of Windows clipboard history and clears them later."""

    WINDOWS_FORMATS = {
        "ExcludeClipboardContentFromMonitorProcessing": b"\x00\x00\x00\x00",
        "CanIncludeInClipboardHistory": b"\x00\x00\x00\x00",
        "CanUploadToCloudClipboard": b"\x00\x00\x00\x00",
    }

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._last: str | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear_if_ours)

    def copy(self, text: str, clear_after_seconds: int, secret: bool = True) -> None:
        mime = QMimeData()
        mime.setText(text)
        if secret and platform.IS_WINDOWS:
            for fmt, value in self.WINDOWS_FORMATS.items():
                mime.setData(f'application/x-qt-windows-mime;value="{fmt}"', QByteArray(value))
        QGuiApplication.clipboard().setMimeData(mime)
        if secret:
            self._last = text
            if clear_after_seconds > 0:
                self._timer.start(clear_after_seconds * 1000)

    @Slot()
    def clear_if_ours(self) -> None:
        self._timer.stop()
        if self._last is not None:
            clipboard = QGuiApplication.clipboard()
            if clipboard.text() == self._last:
                clipboard.clear()
            self._last = None


class ActivityMonitor(QObject):
    """Emits ``idle`` after the user has not touched the app for ``timeout`` seconds."""

    idle = Signal()
    _EVENTS = {QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.Wheel,
               QEvent.TouchBegin}

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.timeout_seconds = 0
        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._check)

    def start(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        self._last = time.monotonic()
        if timeout_seconds > 0:
            self._timer.start()
        else:
            self._timer.stop()

    def stop(self) -> None:
        self._timer.stop()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt API)
        if event.type() in self._EVENTS:
            self._last = time.monotonic()
        return False

    def _check(self) -> None:
        if self.timeout_seconds > 0 and time.monotonic() - self._last >= self.timeout_seconds:
            self._timer.stop()
            self.idle.emit()


def decode_qr_codes(image: QImage) -> list[str]:
    """Return the text of every QR code found in ``image``."""
    if image.isNull():
        return []
    import zxingcpp  # imported lazily: only needed when scanning

    gray = image.convertToFormat(QImage.Format_Grayscale8)
    width, height, stride = gray.width(), gray.height(), gray.bytesPerLine()
    raw = bytes(gray.constBits())[: stride * height]
    if stride != width:
        raw = b"".join(raw[y * stride : y * stride + width] for y in range(height))
    view = memoryview(raw).cast("B", shape=[height, width])
    results = zxingcpp.read_barcodes(view, formats=zxingcpp.BarcodeFormat.QRCode)
    texts = [r.text for r in results if r.text]
    if not texts and max(width, height) > 2400:
        # Very large screenshots: try again at a lower resolution.
        smaller = image.scaled(width // 2, height // 2)
        return decode_qr_codes(smaller)
    return texts


def grab_screens() -> list[QImage]:
    return [screen.grabWindow(0).toImage() for screen in QGuiApplication.screens()]
