"""Cursor confinement and invisibility management via Win32 API.

Pins cursor to coordinate (0, 0), hides cursor shape, and guarantees clean
restoration upon unlock or unexpected process termination.
"""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
import logging
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

DESKTOP_ALL = 0x01FF


class RECT(ctypes.Structure):
    """Win32 RECT structure."""
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class POINT(ctypes.Structure):
    """Win32 POINT structure."""
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class CursorGuard:
    """Manages OS-level cursor confinement to (0, 0) and visibility suppression.

    Uses user32.ClipCursor to physically restrict hardware and synthetic cursor
    movement to coordinate (0, 0) with zero boundary area, preventing mouse
    interaction with background applications. Suppresses cursor rendering via
    user32.ShowCursor display counter manipulation.

    Registers an atexit fail-safe handler to ensure cursor confinement is always
    released if the process terminates unexpectedly.
    """

    def __init__(self, register_atexit: bool = True) -> None:
        self._lock = threading.Lock()
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

        # Configure ctypes prototypes with 64-bit safety
        self._user32.SetCursorPos.restype = wintypes.BOOL
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

        self._user32.ClipCursor.restype = wintypes.BOOL
        self._user32.ClipCursor.argtypes = [ctypes.c_void_p]

        self._user32.GetClipCursor.restype = wintypes.BOOL
        self._user32.GetClipCursor.argtypes = [ctypes.c_void_p]

        self._user32.GetCursorPos.restype = wintypes.BOOL
        self._user32.GetCursorPos.argtypes = [ctypes.c_void_p]

        self._user32.ShowCursor.restype = ctypes.c_int
        self._user32.ShowCursor.argtypes = [wintypes.BOOL]

        self._user32.OpenInputDesktop.restype = wintypes.HANDLE
        self._user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

        self._user32.SetThreadDesktop.restype = wintypes.BOOL
        self._user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]

        self._is_confined: bool = False
        self._cursor_hidden: bool = False
        self._atexit_registered: bool = False

        self._ensure_input_desktop()

        if register_atexit:
            atexit.register(self.release)
            self._atexit_registered = True

    def _ensure_input_desktop(self) -> bool:
        """Attaches calling thread to active input desktop if necessary."""
        try:
            hdesk = self._user32.OpenInputDesktop(0, False, DESKTOP_ALL)
            if hdesk:
                success = bool(self._user32.SetThreadDesktop(hdesk))
                # Note: We do not call CloseDesktop on a desktop handle currently in use by the thread
                return success
        except Exception as exc:
            logger.debug(f"Input desktop attachment exception: {exc}")
        return False

    def confine_to_zero(self) -> bool:
        """Warps cursor to (0, 0), clips bounds to (0, 0, 0, 0), and hides cursor.

        Returns:
            bool: True if cursor was successfully clipped to (0, 0).
        """
        with self._lock:
            if self._is_confined or self.is_confined():
                self._is_confined = True
                if not self._cursor_hidden:
                    while self._user32.ShowCursor(False) >= 0:
                        pass
                    self._cursor_hidden = True
                return True

            self._ensure_input_desktop()

            # 1. Warp cursor to (0, 0)
            self._user32.SetCursorPos(0, 0)

            # 2. Pin cursor clipping boundary to coordinate (0, 0)
            clip_rect = RECT(0, 0, 0, 0)
            clip_success = bool(self._user32.ClipCursor(ctypes.byref(clip_rect)))
            if not clip_success:
                logger.error("user32.ClipCursor(0, 0, 0, 0) failed")
                return False

            # 3. Ensure cursor is at (0, 0)
            self._user32.SetCursorPos(0, 0)

            # 4. Hide cursor via thread display counter if not already hidden
            if not self._cursor_hidden:
                while self._user32.ShowCursor(False) >= 0:
                    pass
                self._cursor_hidden = True

            self._is_confined = True
            logger.debug("Cursor successfully confined to (0, 0) and hidden")
            return True

    def confine_to_rect(self, left: int, top: int, right: int, bottom: int) -> bool:
        """Confines cursor within a specific bounding rectangle and makes it visible.

        Args:
            left, top, right, bottom: Coordinates of the allowed boundary box.

        Returns:
            bool: True if clipping succeeded.
        """
        with self._lock:
            self._ensure_input_desktop()

            # Ensure cursor is visible so user can see it within the dialog
            if self._cursor_hidden:
                while self._user32.ShowCursor(True) < 0:
                    pass
                self._cursor_hidden = False

            # Warp cursor to center of dialog
            cx = (left + right) // 2
            cy = (top + bottom) // 2
            self._user32.SetCursorPos(cx, cy)

            # Pin clipping bounds
            clip_rect = RECT(left, top, right, bottom)
            success = bool(self._user32.ClipCursor(ctypes.byref(clip_rect)))
            self._is_confined = True
            return success

    def release(self) -> bool:
        """Restores unrestricted cursor movement across all displays and shows cursor.

        Returns:
            bool: True if ClipCursor(None) succeeded.
        """
        with self._lock:
            self._ensure_input_desktop()

            # 1. Release cursor clipping (passing NULL/None restores desktop bounds)
            release_success = bool(self._user32.ClipCursor(None))
            if not release_success:
                logger.warning("user32.ClipCursor(None) returned False during release")

            # 2. Restore cursor visibility unconditionally (counter must be >= 0)
            while self._user32.ShowCursor(True) < 0:
                pass
            self._cursor_hidden = False

            self._is_confined = False
            logger.debug("Cursor confinement released and cursor visibility restored")
            return release_success

    def is_confined(self) -> bool:
        """Queries Windows user32 to verify cursor confinement to (0, 0).

        Checks both the active cursor clipping rectangle and current cursor position.

        Returns:
            bool: True if cursor clip rectangle is (0, 0, 0, 0) and position is (0, 0).
        """
        clip_rect = RECT()
        if not self._user32.GetClipCursor(ctypes.byref(clip_rect)):
            return False

        is_zero_rect = (
            clip_rect.left == 0
            and clip_rect.top == 0
            and clip_rect.right == 0
            and clip_rect.bottom == 0
        )
        if not is_zero_rect:
            return False

        pos = POINT()
        if not self._user32.GetCursorPos(ctypes.byref(pos)):
            self._ensure_input_desktop()
            if not self._user32.GetCursorPos(ctypes.byref(pos)):
                return self._is_confined

        return pos.x == 0 and pos.y == 0

    def get_clip_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """Returns the current cursor clipping rectangle as (left, top, right, bottom)."""
        rect = RECT()
        if self._user32.GetClipCursor(ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right, rect.bottom)
        return None

    def get_cursor_pos(self) -> Optional[Tuple[int, int]]:
        """Returns the current cursor position as (x, y)."""
        pos = POINT()
        if not self._user32.GetCursorPos(ctypes.byref(pos)):
            self._ensure_input_desktop()
            if not self._user32.GetCursorPos(ctypes.byref(pos)):
                return None
        return (pos.x, pos.y)

    @property
    def is_cursor_hidden(self) -> bool:
        """Returns whether the cursor is currently marked hidden by this guard."""
        return self._cursor_hidden

    # Contract alias for 1:1 parity with OverlayManager
    confine_cursor = confine_to_zero

    def __enter__(self) -> CursorGuard:
        self.confine_to_zero()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
