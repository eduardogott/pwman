"""Windows-specific integrations. Every function is a safe no-op on other systems."""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
NOTIFY_FOR_THIS_SESSION = 0
WDA_NONE = 0x0
WDA_MONITOR = 0x1
WDA_EXCLUDEFROMCAPTURE = 0x11
VK_CAPITAL = 0x14

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    _user32.GetKeyState.argtypes = [ctypes.c_int]
    _user32.GetKeyState.restype = ctypes.c_short
    try:
        _wtsapi = ctypes.WinDLL("wtsapi32")
        _wtsapi.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
        _wtsapi.WTSRegisterSessionNotification.restype = wintypes.BOOL
    except OSError:  # pragma: no cover
        _wtsapi = None


def set_capture_protection(win_id: int, enabled: bool) -> bool:
    """Hide a window from screenshots/screen sharing (Windows 10 2004+)."""
    if not IS_WINDOWS:
        return False
    hwnd = wintypes.HWND(int(win_id))
    if not enabled:
        return bool(_user32.SetWindowDisplayAffinity(hwnd, WDA_NONE))
    if _user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
        return True
    return bool(_user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR))  # older Windows: black box


def register_session_notifications(win_id: int) -> bool:
    if not IS_WINDOWS or _wtsapi is None:
        return False
    return bool(_wtsapi.WTSRegisterSessionNotification(wintypes.HWND(int(win_id)),
                                                       NOTIFY_FOR_THIS_SESSION))


def is_session_lock_message(event_type, message) -> bool:
    """True if a native Windows message says the workstation was just locked."""
    if not IS_WINDOWS:
        return False
    try:
        if bytes(event_type) != b"windows_generic_MSG":
            return False
        msg = wintypes.MSG.from_address(int(message))
        return msg.message == WM_WTSSESSION_CHANGE and msg.wParam == WTS_SESSION_LOCK
    except Exception:  # never let a parsing problem break the event loop
        return False


def caps_lock_on() -> bool:
    if not IS_WINDOWS:
        return False
    return bool(_user32.GetKeyState(VK_CAPITAL) & 1)
