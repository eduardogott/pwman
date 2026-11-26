import sys

import pytest

from pwman.ui import platform

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only integration")


def _msg_address(message, wparam):
    import ctypes
    from ctypes import wintypes

    msg = wintypes.MSG()
    msg.message = message
    msg.wParam = wparam
    return msg, ctypes.addressof(msg)


def test_session_lock_message_detected():
    msg, addr = _msg_address(platform.WM_WTSSESSION_CHANGE, platform.WTS_SESSION_LOCK)
    assert platform.is_session_lock_message(b"windows_generic_MSG", addr)


def test_other_messages_ignored():
    msg, addr = _msg_address(platform.WM_WTSSESSION_CHANGE, 0x8)  # session unlock
    assert not platform.is_session_lock_message(b"windows_generic_MSG", addr)
    msg2, addr2 = _msg_address(0x0001, platform.WTS_SESSION_LOCK)  # WM_CREATE
    assert not platform.is_session_lock_message(b"windows_generic_MSG", addr2)
    assert not platform.is_session_lock_message(b"something_else", addr)


def test_caps_lock_query_does_not_crash():
    assert platform.caps_lock_on() in (True, False)
