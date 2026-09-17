"""Hook lifecycle and desktop-attached input interception manager.

This module coordinates low-level Windows keyboard and mouse hooks, ensuring
proper Win32 interactive desktop attachment (OpenInputDesktop/SetThreadDesktop)
and persistent ultra-low-latency event suppression.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from typing import Any, Callable, Optional

from pynput import keyboard, mouse

from input_locker.hooks.event_filter import EventFilter

logger = logging.getLogger(__name__)

# User32 handle for desktop attachment
try:
    user32 = ctypes.windll.user32
    HAS_USER32 = True
except Exception:  # pragma: no cover
    user32 = None
    HAS_USER32 = False


def attach_input_desktop() -> bool:
    """Attach the calling thread to the active interactive input desktop.
    
    In headless, CI, or secondary desktop environments (e.g. test runners),
    threads default to non-interactive or child desktops. Attaching to the
    input desktop via OpenInputDesktop is required for low-level hooks and
    SendInput synthetic input to operate without ERROR_ACCESS_DENIED (5).
    
    Returns:
        bool: True if attached or already on input desktop, False on failure.
    """
    if not HAS_USER32 or user32 is None:
        return False
    try:
        # 0x01FF = MAXIMUM_ALLOWED access mask
        h_input = user32.OpenInputDesktop(0, False, 0x01FF)
        if h_input:
            success = bool(user32.SetThreadDesktop(h_input))
            if success:
                logger.debug("Successfully attached thread to input desktop (handle=%s)", h_input)
            return success
    except Exception as exc:
        logger.debug("Desktop attachment exception: %s", exc)
    return False


class DesktopAttachedKeyboardListener(keyboard.Listener):
    """pynput keyboard.Listener that attaches to the active input desktop."""

    def _run(self) -> None:
        attach_input_desktop()
        super()._run()


class DesktopAttachedMouseListener(mouse.Listener):
    """pynput mouse.Listener that attaches to the active input desktop."""

    def _run(self) -> None:
        attach_input_desktop()
        super()._run()


class HookManager:
    """Manages persistent low-level keyboard and mouse hooks.
    
    Implements the M1 (Hooks) <-> M3 (State Machine) contract from PROJECT.md:
    - start(): Starts persistent hook threads attached to input desktop.
    - stop(): Cleanly unhooks and terminates listener threads.
    - set_swallow(active: bool): Atomic toggle to swallow or pass through input.
    - is_swallowing() -> bool: Returns current swallowing state.
    """

    def __init__(
        self,
        on_lock_hotkey: Optional[Callable[[], None]] = None,
        on_unlock_hotkey: Optional[Callable[[], None]] = None,
        swallow_active: bool = False,
    ) -> None:
        self._on_lock_hotkey = on_lock_hotkey
        self._on_unlock_hotkey = on_unlock_hotkey
        self._swallow_active: bool = bool(swallow_active)

        self._event_filter: EventFilter = EventFilter(
            on_lock_hotkey=self._on_lock_hotkey,
            on_unlock_hotkey=self._on_unlock_hotkey,
            swallow_active=self._swallow_active,
        )

        self._keyboard_listener: Optional[DesktopAttachedKeyboardListener] = None
        self._mouse_listener: Optional[DesktopAttachedMouseListener] = None
        self._running: bool = False
        self._lock: threading.Lock = threading.Lock()

    @property
    def event_filter(self) -> EventFilter:
        """Return the underlying EventFilter instance."""
        return self._event_filter

    @property
    def is_running(self) -> bool:
        """Return True if hook listeners are currently running."""
        return self._running

    def is_swallowing(self) -> bool:
        """Return current input swallowing state."""
        return self._event_filter.is_swallowing()

    def set_swallow(self, active: bool) -> None:
        """Atomically toggle swallowing state.
        
        Args:
            active: If True, all keyboard and mouse inputs are swallowed.
        """
        self._swallow_active = bool(active)
        self._event_filter.set_swallow(self._swallow_active)
        logger.info("Hook swallowing state updated: swallow_active=%s", self._swallow_active)

    def set_password_mode(self, active: bool) -> None:
        """Toggle password entry mode in the event filter.

        When active, system keys (Alt+Tab, Win, Alt+Esc, Ctrl+Esc) remain strictly swallowed.
        """
        self._event_filter.set_password_mode(active)
        logger.info("Hook password mode updated: active=%s", active)

    def start(self) -> None:
        """Start persistent keyboard and mouse hook threads.
        
        Attaches calling thread and worker threads to the active input desktop.
        Blocks until both hooks are fully installed and ready in Windows.
        """
        with self._lock:
            if self._running:
                logger.warning("HookManager already running; ignoring start()")
                return

            attach_input_desktop()

            # Ensure filter has latest callbacks and swallow state
            self._event_filter.set_swallow(self._swallow_active)

            self._keyboard_listener = DesktopAttachedKeyboardListener(
                win32_event_filter=self._event_filter.keyboard_event_filter
            )
            self._mouse_listener = DesktopAttachedMouseListener(
                win32_event_filter=self._event_filter.mouse_event_filter
            )

            self._event_filter.set_listeners(
                keyboard_listener=self._keyboard_listener,
                mouse_listener=self._mouse_listener,
            )

            logger.info("Starting desktop-attached keyboard and mouse listeners...")
            self._keyboard_listener.start()
            self._mouse_listener.start()

            # Wait for Windows hook procedures to be fully registered
            if hasattr(self._keyboard_listener, "wait"):
                self._keyboard_listener.wait()
            if hasattr(self._mouse_listener, "wait"):
                self._mouse_listener.wait()

            self._running = True
            logger.info("HookManager started successfully.")

    def stop(self) -> None:
        """Cleanly unhook and terminate listener threads."""
        with self._lock:
            if not self._running:
                return

            logger.info("Stopping HookManager listeners...")
            if self._keyboard_listener is not None:
                try:
                    self._keyboard_listener.stop()
                except Exception as exc:
                    logger.debug("Error stopping keyboard listener: %s", exc)

            if self._mouse_listener is not None:
                try:
                    self._mouse_listener.stop()
                except Exception as exc:
                    logger.debug("Error stopping mouse listener: %s", exc)

            # Wait for threads to terminate cleanly
            if self._keyboard_listener is not None and self._keyboard_listener.is_alive():
                self._keyboard_listener.join(timeout=2.0)
            if self._mouse_listener is not None and self._mouse_listener.is_alive():
                self._mouse_listener.join(timeout=2.0)

            self._keyboard_listener = None
            self._mouse_listener = None
            self._event_filter.set_listeners(None, None)
            self._running = False
            logger.info("HookManager stopped cleanly.")

    def __enter__(self) -> HookManager:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
