"""Win32 low-level hook event filter callbacks for keyboard and mouse.

This module provides high-performance, deterministic event filtering and
swallowing for the Windows AV Staging Input Locker. It monitors global inputs
via low-level OS hooks, executes in-filter hotkey recognition, and suppresses
keyboard and mouse events system-wide.
"""

from __future__ import annotations

import ctypes
import logging
from typing import Any, Callable, Collection, Iterable, Optional, Set

logger = logging.getLogger(__name__)

# Virtual Key Constants
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt key
VK_F11 = 0x7A
VK_U = 0x55

VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4  # Left Alt
VK_RMENU = 0xA5  # Right Alt

# Key code groupings for modifier checks
CTRL_KEYS = {VK_CONTROL, VK_LCONTROL, VK_RCONTROL}
ALT_KEYS = {VK_MENU, VK_LMENU, VK_RMENU}
SHIFT_KEYS = {VK_SHIFT, VK_LSHIFT, VK_RSHIFT}

# Windows Message Identifiers
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E

# Import pynput's internal SuppressException for direct raising if needed
try:
    from pynput._util.win32 import SystemHook
    SuppressException = SystemHook.SuppressException
except Exception:  # pragma: no cover
    class SuppressException(Exception):
        """Fallback SuppressException when pynput win32 is unavailable."""
        pass

# Optional Win32 user32 handle for hardware async key state checks
try:
    user32 = ctypes.windll.user32
    HAS_USER32 = True
except Exception:  # pragma: no cover
    user32 = None
    HAS_USER32 = False


class EventFilter:
    """Low-level hook event filter evaluating hotkeys and input suppression.
    
    Attributes:
        on_lock_hotkey: Callback invoked when F11 is pressed.
        on_unlock_hotkey: Callback invoked when Ctrl+Alt+Shift+U is pressed.
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
        self._password_mode: bool = False

        self._active_keys: Set[int] = set()
        self._pending_unlock_keyups: Set[int] = set()
        self._keyboard_listener: Any = None
        self._mouse_listener: Any = None

        # Diagnostics & verification metrics
        self.swallowed_keyboard_count: int = 0
        self.swallowed_mouse_count: int = 0
        self.total_keyboard_count: int = 0
        self.total_mouse_count: int = 0

    @property
    def swallow_active(self) -> bool:
        """Atomic lock-free check of the current swallowing state."""
        return self._swallow_active

    @property
    def password_mode(self) -> bool:
        """Return True if password entry mode is currently active."""
        return self._password_mode

    def set_password_mode(self, active: bool) -> None:
        """Enable or disable password entry mode.

        When active, system task-switching shortcuts (Alt+Tab, Win, Alt+Esc, Ctrl+Esc)
        remain strictly suppressed to prevent switching to background apps,
        while normal text input keys reach the password prompt.
        """
        self._password_mode = bool(active)
        logger.debug("EventFilter password_mode set to %s", self._password_mode)

    def set_swallow(self, active: bool) -> None:
        """Atomically toggle swallowing state.
        
        Args:
            active: If True, all keyboard and mouse inputs are swallowed.
        """
        self._swallow_active = bool(active)
        if not self._swallow_active:
            # Clear tracked keys on unlock transition to prevent stuck modifiers
            self._active_keys.clear()

    def is_swallowing(self) -> bool:
        """Return True if currently swallowing inputs."""
        return self._swallow_active

    def set_listeners(
        self,
        keyboard_listener: Any = None,
        mouse_listener: Any = None,
    ) -> None:
        """Attach listener references for event suppression dispatch."""
        self._keyboard_listener = keyboard_listener
        self._mouse_listener = mouse_listener

    @property
    def active_keys(self) -> Set[int]:
        """Return a copy of currently tracked pressed virtual key codes."""
        return set(self._active_keys)

    @property
    def pending_unlock_keyups(self) -> Set[int]:
        """Return a copy of currently pending unlock keyups to be swallowed."""
        return set(self._pending_unlock_keyups)

    def suppress_keyboard(self) -> None:
        """Suppress the current keyboard event from Windows and foreground apps."""
        self.swallowed_keyboard_count += 1
        if self._keyboard_listener is not None and hasattr(self._keyboard_listener, "suppress_event"):
            self._keyboard_listener.suppress_event()
        else:
            raise SuppressException()

    def suppress_mouse(self) -> None:
        """Suppress the current mouse event from Windows and foreground apps."""
        self.swallowed_mouse_count += 1
        if self._mouse_listener is not None and hasattr(self._mouse_listener, "suppress_event"):
            self._mouse_listener.suppress_event()
        else:
            raise SuppressException()

    def _query_async_keystate(self, vkeys: Collection[int]) -> bool:
        """Query Win32 GetAsyncKeyState for hardware key down status."""
        if not HAS_USER32 or user32 is None:
            return False
        try:
            for vk in vkeys:
                if user32.GetAsyncKeyState(vk) & 0x8000:
                    return True
        except Exception:
            pass
        return False

    def keyboard_event_filter(self, msg: int, data: Any) -> bool:
        """Win32 low-level keyboard hook callback procedure.
        
        Evaluates hotkeys and determines whether the event should be swallowed.
        Note: If suppress_keyboard() is called, it raises SuppressException,
        which pynput catches to return 1 to Windows, halting event propagation.
        
        Args:
            msg: Windows message code (e.g. WM_KEYDOWN, WM_SYSKEYDOWN).
            data: Pointer/struct to KBDLLHOOKSTRUCT containing vkCode.
            
        Returns:
            bool: True to allow pynput to continue (when not suppressed).
        """
        self.total_keyboard_count += 1

        # Extract virtual key code
        vk = getattr(data, "vkCode", None)
        if vk is None:
            if isinstance(data, int):
                vk = data
            elif isinstance(data, dict):
                vk = data.get("vkCode")
            else:
                return True

        is_down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = msg in (WM_KEYUP, WM_SYSKEYUP)

        if is_down:
            self._active_keys.add(vk)
        elif is_up:
            self._active_keys.discard(vk)
            # Clear entire modifier family on any modifier keyup to prevent sticky state
            if vk in CTRL_KEYS:
                self._active_keys.difference_update(CTRL_KEYS)
            elif vk in ALT_KEYS:
                self._active_keys.difference_update(ALT_KEYS)
            elif vk in SHIFT_KEYS:
                self._active_keys.difference_update(SHIFT_KEYS)

        # Check for pending unlock keyups: swallow release of combo/modifier keys
        # even after the state machine has unlocked (swallow_active == False).
        is_pending_keyup = False
        if is_up and self._pending_unlock_keyups:
            if vk in self._pending_unlock_keyups:
                self._pending_unlock_keyups.discard(vk)
                is_pending_keyup = True
            if vk in CTRL_KEYS:
                if bool(self._pending_unlock_keyups & CTRL_KEYS):
                    self._pending_unlock_keyups.difference_update(CTRL_KEYS)
                    is_pending_keyup = True
            elif vk in ALT_KEYS:
                if bool(self._pending_unlock_keyups & ALT_KEYS):
                    self._pending_unlock_keyups.difference_update(ALT_KEYS)
                    is_pending_keyup = True
            elif vk in SHIFT_KEYS:
                if bool(self._pending_unlock_keyups & SHIFT_KEYS):
                    self._pending_unlock_keyups.difference_update(SHIFT_KEYS)
                    is_pending_keyup = True

        # 1. Hotkey Detection: Lock Hotkey F11
        if vk == VK_F11 and is_down:
            if self._on_lock_hotkey is not None:
                try:
                    self._on_lock_hotkey()
                except Exception as exc:
                    logger.error("Error executing on_lock_hotkey: %s", exc, exc_info=True)

        # 2. Hotkey Detection: Unlock Combo Ctrl + Alt + Shift + U
        is_unlock_combo = False
        if vk == VK_U and is_down:
            # Strictly verify simultaneous presence in _active_keys without async OS polling
            ctrl = bool(self._active_keys & CTRL_KEYS)
            alt = bool(self._active_keys & ALT_KEYS)
            shift = bool(self._active_keys & SHIFT_KEYS)

            if ctrl and alt and shift:
                is_unlock_combo = True

                # Record currently held keys and all modifier variants for post-unlock swallowing
                self._pending_unlock_keyups.update(self._active_keys)
                self._pending_unlock_keyups.add(vk)
                self._pending_unlock_keyups.update(CTRL_KEYS)
                self._pending_unlock_keyups.update(ALT_KEYS)
                self._pending_unlock_keyups.update(SHIFT_KEYS)

                if self._on_unlock_hotkey is not None:
                    try:
                        self._on_unlock_hotkey()
                    except Exception as exc:
                        logger.error("Error executing on_unlock_hotkey: %s", exc, exc_info=True)

        # In password entry mode, suppress system task-switching shortcuts so background apps cannot be accessed
        is_task_switch = False
        if self._password_mode:
            is_task_switch = (
                # Alt + Tab (VK_TAB = 0x09)
                (vk == 0x09 and bool(self._active_keys & ALT_KEYS))
                # Windows keys (VK_LWIN = 0x5B, VK_RWIN = 0x5C)
                or (vk in (0x5B, 0x5C))
                # Ctrl + Esc (Start menu)
                or (vk == 0x1B and bool(self._active_keys & CTRL_KEYS))
                # Alt + Esc (Direct window cycling)
                or (vk == 0x1B and bool(self._active_keys & ALT_KEYS))
                # Alt + Space (Window system menu)
                or (vk == 0x20 and bool(self._active_keys & ALT_KEYS))
            )

        # 3. Swallowing Determination & Win+L Neutralization:
        # - While locked, if Windows key (0x5B, 0x5C) is pressed, immediately synthesize keyup
        #   so Windows kernel does not register a held Win key or trigger Win+L workstation lock.
        if self._swallow_active and HAS_USER32 and user32 is not None:
            if vk in (0x5B, 0x5C) and is_down:
                try:
                    user32.keybd_event(vk, 0, 0x0002, 0)
                except Exception:
                    pass
            elif vk == 0x4C and bool(self._active_keys & {0x5B, 0x5C}):
                try:
                    user32.keybd_event(0x5B, 0, 0x0002, 0)
                    user32.keybd_event(0x5C, 0, 0x0002, 0)
                except Exception:
                    pass

        # - F11 is always swallowed (even when unlocked) to protect staging media players
        # - When locked (swallow_active is True), ALL keys are swallowed
        # - When in password_mode, task-switching combos (Alt+Tab, Win keys, etc.) are swallowed
        # - When unlock combo 'U' is pressed, it must be swallowed so 'U' doesn't leak
        # - Subsequent keyups from the unlock combo are swallowed even if swallow_active is False
        should_swallow = (
            self._swallow_active
            or (vk == VK_F11)
            or is_unlock_combo
            or is_pending_keyup
            or is_task_switch
        )

        if should_swallow:
            self.suppress_keyboard()

        return True

    def mouse_event_filter(self, msg: int, data: Any) -> bool:
        """Win32 low-level mouse hook callback procedure.
        
        Suppresses all mouse events (movements, clicks, scrolls) when
        swallow_active is True.
        
        Args:
            msg: Windows mouse message code.
            data: MSLLHOOKSTRUCT or event data.
            
        Returns:
            bool: True when not suppressed.
        """
        self.total_mouse_count += 1

        if self._swallow_active:
            self.suppress_mouse()

        return True
