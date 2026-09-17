"""Unified Overlay and Cursor Confinement Manager.

Coordinates the non-activating semi-transparent glass overlay (Win32 / PyQt6) and
Win32 cursor confinement (ClipCursor & ShowCursor) to provide a seamless, focus-preserving
locked state for live AV staging environments.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Tuple

from input_locker.overlay.cursor_guard import CursorGuard
from input_locker.overlay.win32_overlay import Win32Overlay
from input_locker.overlay.pyqt_overlay import PyQtOverlay, PYQT6_AVAILABLE

logger = logging.getLogger(__name__)


class OverlayManager:
    """Unified coordinator implementing the M2 overlay and cursor confinement contract.

    Adheres to the interface contract defined in PROJECT.md:
        - prewarm(): Pre-creates transparent non-activating window(s) in hidden state.
        - show_overlay(): Shows full-screen overlay without focus stealing.
        - hide_overlay(): Hides overlay without focus recalculation.
        - confine_cursor(): Warps cursor to (0, 0), clips to (0, 0, 0, 0), hides cursor.
        - release_cursor(): Restores cursor clipping and unhides cursor.

    Also provides combined lock() and unlock() workflows following the surveyed
    optimal operation order.
    """

    def __init__(
        self,
        backend: str = "pyqt",
        alpha: int = 120,
        auto_prewarm: bool = True,
        wallpaper: str = "",
    ) -> None:
        """Initialize the OverlayManager.

        Args:
            backend: Overlay rendering backend: 'pyqt' (default, rich badge) or 'win32'.
            alpha: Transparency alpha (0-255). Default 120 (~47% tint).
            auto_prewarm: Whether to immediately pre-create the hidden overlay window.
            wallpaper: Optional absolute path to a wallpaper image for the lock screen.
        """
        self.backend_name = backend.lower()
        self.alpha = alpha
        self._lock = threading.Lock()

        # Instantiate cursor guard with fail-safe atexit release
        self.cursor_guard = CursorGuard(register_atexit=True)

        # Instantiate selected overlay backend
        if self.backend_name in ("pyqt", "pyqt6"):
            if not PYQT6_AVAILABLE:
                logger.warning("PyQt6 requested but not available; falling back to win32 backend")
                self.overlay = Win32Overlay(alpha=self.alpha, auto_prewarm=auto_prewarm)
                self.backend_name = "win32"
            else:
                self.overlay = PyQtOverlay(auto_prewarm=auto_prewarm, wallpaper_path=wallpaper)
        else:
            self.overlay = Win32Overlay(alpha=self.alpha, auto_prewarm=auto_prewarm)
            self.backend_name = "win32"

    def prewarm(self) -> None:
        """Pre-creates the overlay window(s) in hidden state to eliminate show latency."""
        with self._lock:
            self.overlay.prewarm()

    def show_overlay(self) -> bool:
        """Shows the full-screen overlay without stealing or altering window focus.

        Uses SWP_NOACTIVATE | SWP_SHOWWINDOW with HWND_TOPMOST (or WA_ShowWithoutActivating)
        to guarantee 0 WM_ACTIVATE / WM_KILLFOCUS events on background applications.

        Returns:
            bool: True if overlay was successfully displayed.
        """
        with self._lock:
            return self.overlay.show()

    def hide_overlay(self) -> bool:
        """Hides the overlay window without causing focus recalculation.

        Uses SWP_HIDEWINDOW | SWP_NOACTIVATE.

        Returns:
            bool: True if overlay was successfully hidden.
        """
        with self._lock:
            return self.overlay.hide()

    def confine_cursor(self) -> bool:
        """Warps cursor to (0, 0), clips bounds to (0, 0, 0, 0), and hides cursor shape.

        Returns:
            bool: True if cursor was successfully pinned and hidden.
        """
        with self._lock:
            return self.cursor_guard.confine_to_zero()

    def release_cursor(self) -> bool:
        """Restores unrestricted cursor movement across all displays and unhides cursor.

        Returns:
            bool: True if cursor was successfully released.
        """
        with self._lock:
            return self.cursor_guard.release()

    def lock(self) -> bool:
        """Executes full lock activation sequence.

        Surveyed optimal sequence:
        1. Confine and hide cursor (confine_cursor)
        2. Show non-activating overlay (show_overlay)

        Returns:
            bool: True if both confinement and overlay show succeeded.
        """
        with self._lock:
            cursor_ok = self.cursor_guard.confine_to_zero()
            overlay_ok = self.overlay.show()
            return cursor_ok and overlay_ok

    def unlock(self) -> bool:
        """Executes full unlock deactivation sequence.

        Surveyed optimal sequence:
        1. Hide overlay (hide_overlay)
        2. Release cursor bounds and restore visibility (release_cursor)

        Returns:
            bool: True if both overlay hide and cursor release succeeded.
        """
        with self._lock:
            overlay_ok = self.overlay.hide()
            cursor_ok = self.cursor_guard.release()
            return overlay_ok and cursor_ok

    def is_locked(self) -> bool:
        """Returns True if both the overlay is visible and cursor is confined."""
        return self.is_overlay_visible() and self.is_cursor_confined()

    def is_overlay_visible(self) -> bool:
        """Returns True if the overlay window is currently visible."""
        return self.overlay.is_visible()

    def is_cursor_confined(self) -> bool:
        """Returns True if the cursor is currently confined to (0, 0)."""
        return self.cursor_guard.is_confined()

    def get_geometry(self) -> Tuple[int, int, int, int]:
        """Returns the virtual screen / overlay geometry as (x, y, width, height)."""
        return self.overlay.get_geometry()

    def close(self) -> None:
        """Cleanly releases cursor confinement and destroys overlay resources."""
        with self._lock:
            self.cursor_guard.release()
            self.overlay.close()

    def __enter__(self) -> OverlayManager:
        self.prewarm()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
