"""Single-instance process management for Input Locker.

Uses a Win32 Named Mutex to prevent duplicate processes from launching, and
a Win32 Named Event to bring the existing window to the foreground or trigger
settings if the user launches a second instance.
"""
from __future__ import annotations

import ctypes
import logging
import threading
from typing import Callable, Optional

from ctypes import wintypes

logger = logging.getLogger(__name__)

MUTEX_NAME = "Local\\InputLocker_SingleInstance_Mutex_2026"
EVENT_NAME = "Local\\InputLocker_ShowSettings_Event_2026"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0

_kernel32 = ctypes.windll.kernel32
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE

_kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE

_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE

_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.SetEvent.restype = wintypes.BOOL

_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD

_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


def _bring_to_front(hwnd) -> bool:
    """Brings hwnd to the foreground bypassing OS focus stealing prevention."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Un-minimize if minimized
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

        fore_hwnd = user32.GetForegroundWindow()
        if fore_hwnd != hwnd:
            fore_thread = user32.GetWindowThreadProcessId(fore_hwnd, None)
            cur_thread = kernel32.GetCurrentThreadId()
            if fore_thread != cur_thread:
                user32.AttachThreadInput(cur_thread, fore_thread, True)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.AttachThreadInput(cur_thread, fore_thread, False)

        return True
    except Exception as exc:
        logger.debug("Error in _bring_to_front: %s", exc)
        return False


def focus_existing_window() -> bool:
    """Finds and restores/focuses any existing Input Locker window."""
    try:
        user32 = ctypes.windll.user32

        # Allow target window process to take foreground
        try:
            user32.AllowSetForegroundWindow(ctypes.c_uint(-1))
        except Exception:
            pass

        # Direct title lookups
        for title in ("Input Locker — Settings", "Input Locker - Settings"):
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                return _bring_to_front(hwnd)

        # Fallback: scan top-level windows for "Input Locker"
        found = []

        def _enum_proc(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                text = buf.value
                
                class_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buf, 256)
                cls_name = class_buf.value
                
                if "Input Locker" in text and cls_name == "TkTopLevel":
                    found.append(hwnd)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.py_object)
        user32.EnumWindows(WNDENUMPROC(_enum_proc), found)

        if found:
            return _bring_to_front(found[0])
    except Exception as exc:
        logger.debug("Error while focusing existing window: %s", exc)

    return False


class SingleInstanceManager:
    """Manages single-instance lifecycle using named Win32 Mutex and Event."""

    def __init__(self, mutex_name: str = MUTEX_NAME, event_name: str = EVENT_NAME) -> None:
        self.mutex_name = mutex_name
        self.event_name = event_name
        self._mutex_handle = None
        self._event_handle = None
        self._listener_thread: Optional[threading.Thread] = None

    def acquire(self) -> bool:
        """Attempt to acquire single-instance ownership.

        Returns:
            True if this is the first running instance.
            False if another instance is already running.
        """
        try:
            handle = _kernel32.CreateMutexW(None, False, self.mutex_name)
            last_err = _kernel32.GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                if handle:
                    _kernel32.CloseHandle(handle)
                return False

            self._mutex_handle = handle
            # Also create the named event for IPC communication from secondary instances
            self._event_handle = _kernel32.CreateEventW(None, False, False, self.event_name)
            return True
        except Exception as exc:
            logger.warning("Single-instance check encountered error: %s; allowing launch.", exc)
            return True

    def notify_existing_instance(self) -> None:
        """Brings existing window to front and signals running instance."""
        # 1. Signal the named event so the running background process can open settings
        try:
            h_event = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, self.event_name)
            if h_event:
                ok = _kernel32.SetEvent(h_event)
                logger.info("SetEvent returned %s on event handle %s", ok, h_event)
                _kernel32.CloseHandle(h_event)
            else:
                logger.warning("OpenEventW failed for %s: %s", self.event_name, ctypes.GetLastError())
        except Exception as exc:
            logger.debug("Could not signal existing instance event: %s", exc)

        # 2. Try to focus existing window if already open
        focus_existing_window()

    def start_listener(self, on_request_callback: Callable[[], None], shutdown_event: threading.Event) -> None:
        """Starts a background thread listening for requests from secondary launches."""
        if not self._event_handle:
            logger.warning("No event handle for single instance listener!")
            return

        def _listen():
            while not shutdown_event.is_set():
                res = _kernel32.WaitForSingleObject(self._event_handle, 500)
                if res == WAIT_OBJECT_0:
                    logger.info("SingleInstanceListener detected signal from secondary instance!")
                    try:
                        on_request_callback()
                    except Exception as exc:
                        logger.warning("Error in single-instance request callback: %s", exc)

        t = threading.Thread(target=_listen, daemon=True, name="SingleInstanceListener")
        t.start()
        self._listener_thread = t

    def release(self) -> None:
        """Releases Win32 handles."""
        if self._event_handle:
            try:
                _kernel32.CloseHandle(self._event_handle)
            except Exception:
                pass
            self._event_handle = None

        if self._mutex_handle:
            try:
                _kernel32.CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None
