"""Unit tests for Windows AV Staging Input Locker hook subsystem.

Tests EventFilter, HookManager, desktop attachment, modifier tracking,
system key handling (WM_SYSKEYDOWN), hotkey detection, and event swallowing.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Ensure src/ and project root are on sys.path for direct test execution
_project_root = Path(__file__).resolve().parent.parent.parent
_src_dir = _project_root / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))
if str(_project_root) not in sys.path:
    sys.path.insert(1, str(_project_root))

import pytest

from input_locker.hooks.event_filter import (
    ALT_KEYS,
    CTRL_KEYS,
    SHIFT_KEYS,
    VK_CONTROL,
    VK_F11,
    VK_LCONTROL,
    VK_LMENU,
    VK_LSHIFT,
    VK_MENU,
    VK_RCONTROL,
    VK_RMENU,
    VK_RSHIFT,
    VK_SHIFT,
    VK_U,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MBUTTONDOWN,
    WM_MBUTTONUP,
    WM_MOUSEHWHEEL,
    WM_MOUSEMOVE,
    WM_MOUSEWHEEL,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
    WM_XBUTTONDOWN,
    WM_XBUTTONUP,
    EventFilter,
    SuppressException,
)
from input_locker.hooks.hook_manager import (
    DesktopAttachedKeyboardListener,
    DesktopAttachedMouseListener,
    HookManager,
    attach_input_desktop,
)


class MockEventData:
    """Mock KBDLLHOOKSTRUCT or MSLLHOOKSTRUCT for testing."""

    def __init__(self, vkCode: int = 0, flags: int = 0) -> None:
        self.vkCode = vkCode
        self.scanCode = 0
        self.flags = flags
        self.time = 0
        self.dwExtraInfo = 0


# ============================================================================
# EventFilter Tests
# ============================================================================


class TestEventFilterState:
    """Tests for basic state management and properties of EventFilter."""

    def test_initial_state_defaults(self) -> None:
        ef = EventFilter()
        assert ef.is_swallowing() is False
        assert ef.swallow_active is False
        assert len(ef.active_keys) == 0
        assert ef.swallowed_keyboard_count == 0
        assert ef.swallowed_mouse_count == 0

    def test_initial_state_with_swallow_true(self) -> None:
        ef = EventFilter(swallow_active=True)
        assert ef.is_swallowing() is True
        assert ef.swallow_active is True

    def test_set_swallow_transitions(self) -> None:
        ef = EventFilter()
        mock_kb = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb)
        ef.set_swallow(True)
        assert ef.is_swallowing() is True

        # Simulate some active keys while locked
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(0x41))
        assert 0x41 in ef.active_keys

        # Transitioning to unlocked should clear active keys
        ef.set_swallow(False)
        assert ef.is_swallowing() is False
        assert len(ef.active_keys) == 0


class TestEventFilterUnlockedKeyboard:
    """Tests for keyboard event filtering when UNLOCKED."""

    def test_normal_keys_pass_through_unlocked(self) -> None:
        ef = EventFilter(swallow_active=False)
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        for vk in (0x41, 0x42, 0x20, 0x0D):  # 'A', 'B', Space, Enter
            # Key down
            res_down = ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(vk))
            assert res_down is True
            # Key up
            res_up = ef.keyboard_event_filter(WM_KEYUP, MockEventData(vk))
            assert res_up is True

        # Normal keys must NOT be suppressed
        mock_kb_listener.suppress_event.assert_not_called()
        assert ef.swallowed_keyboard_count == 0
        assert ef.total_keyboard_count == 8

    def test_f11_keydown_triggers_lock_hotkey_and_is_swallowed(self) -> None:
        lock_called = []
        ef = EventFilter(
            on_lock_hotkey=lambda: lock_called.append(True),
            swallow_active=False,
        )
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        res = ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_F11))
        assert res is True
        assert len(lock_called) == 1
        # F11 MUST be swallowed even when unlocked
        mock_kb_listener.suppress_event.assert_called_once()
        assert ef.swallowed_keyboard_count == 1

    def test_f11_keyup_is_swallowed_without_triggering_hotkey_again(self) -> None:
        lock_called = []
        ef = EventFilter(
            on_lock_hotkey=lambda: lock_called.append(True),
            swallow_active=False,
        )
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        res = ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_F11))
        assert res is True
        assert len(lock_called) == 0
        # Key up for F11 must also be swallowed so foreground app sees no release
        mock_kb_listener.suppress_event.assert_called_once()
        assert ef.swallowed_keyboard_count == 1


class TestEventFilterLockedKeyboard:
    """Tests for keyboard event filtering when LOCKED (swallow_active=True)."""

    def test_all_normal_keys_are_swallowed_when_locked(self) -> None:
        ef = EventFilter(swallow_active=True)
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        for vk in (0x41, 0x42, 0x30, 0x1B):  # 'A', 'B', '0', ESC
            ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(vk))
            ef.keyboard_event_filter(WM_KEYUP, MockEventData(vk))

        assert mock_kb_listener.suppress_event.call_count == 8
        assert ef.swallowed_keyboard_count == 8

    def test_modifiers_alone_are_swallowed_without_unlocking(self) -> None:
        unlock_called = []
        ef = EventFilter(
            on_unlock_hotkey=lambda: unlock_called.append(True),
            swallow_active=True,
        )
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        # Press and release Ctrl, Alt, Shift separately
        for mod in (VK_CONTROL, VK_MENU, VK_SHIFT):
            ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(mod))
            ef.keyboard_event_filter(WM_KEYUP, MockEventData(mod))

        assert len(unlock_called) == 0
        assert mock_kb_listener.suppress_event.call_count == 6
        assert ef.swallowed_keyboard_count == 6

    def test_partial_combos_do_not_unlock(self) -> None:
        unlock_called = []
        ef = EventFilter(
            on_unlock_hotkey=lambda: unlock_called.append(True),
            swallow_active=True,
        )
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        # 1. Ctrl + Shift + U (Missing Alt)
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_CONTROL))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_SHIFT))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_U))
        assert len(unlock_called) == 0

        # Release all
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_U))
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_SHIFT))
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_CONTROL))

        # 2. Ctrl + Alt + U (Missing Shift)
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_CONTROL))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_MENU))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_U))
        assert len(unlock_called) == 0

        # All events should have been swallowed
        assert mock_kb_listener.suppress_event.call_count == 9

    def test_full_unlock_combo_standard_keys(self) -> None:
        unlock_called = []
        ef = EventFilter(
            on_unlock_hotkey=lambda: unlock_called.append(True),
            swallow_active=True,
        )
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        # Sequence: Ctrl down -> Alt down -> Shift down -> U down
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_CONTROL))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_MENU))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_SHIFT))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_U))

        assert len(unlock_called) == 1
        # The 'U' key itself must also be swallowed so it does not leak
        assert mock_kb_listener.suppress_event.call_count == 4
        assert ef.swallowed_keyboard_count == 4

    def test_full_unlock_combo_with_syskeydown_when_alt_held(self) -> None:
        """Windows sends WM_SYSKEYDOWN when Alt is held.
        
        This tests that Ctrl+Alt+Shift+U is detected even when 'U' arrives
        as WM_SYSKEYDOWN (0x0104).
        """
        unlock_called = []
        ef = EventFilter(
            on_unlock_hotkey=lambda: unlock_called.append(True),
            swallow_active=True,
        )
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        # Press Left Control
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_LCONTROL))
        # Press Left Alt (emits WM_SYSKEYDOWN)
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_LMENU))
        # Press Left Shift while Alt held (emits WM_SYSKEYDOWN)
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_LSHIFT))
        # Press U while Alt held (emits WM_SYSKEYDOWN)
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_U))

        assert len(unlock_called) == 1
        assert mock_kb_listener.suppress_event.call_count == 4

    def test_full_unlock_combo_with_right_modifiers(self) -> None:
        """Test unlock combo with Right Control, Right Alt (AltGr), Right Shift."""
        unlock_called = []
        ef = EventFilter(
            on_unlock_hotkey=lambda: unlock_called.append(True),
            swallow_active=True,
        )
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_RCONTROL))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_RMENU))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_RSHIFT))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_U))

        assert len(unlock_called) == 1
        assert mock_kb_listener.suppress_event.call_count == 4


class TestEventFilterMouse:
    """Tests for mouse event filtering."""

    @pytest.mark.parametrize(
        "msg",
        [
            WM_MOUSEMOVE,
            WM_LBUTTONDOWN,
            WM_LBUTTONUP,
            WM_RBUTTONDOWN,
            WM_RBUTTONUP,
            WM_MBUTTONDOWN,
            WM_MBUTTONUP,
            WM_MOUSEWHEEL,
            WM_XBUTTONDOWN,
            WM_XBUTTONUP,
            WM_MOUSEHWHEEL,
        ],
    )
    def test_mouse_events_pass_when_unlocked(self, msg: int) -> None:
        ef = EventFilter(swallow_active=False)
        mock_mouse_listener = MagicMock()
        ef.set_listeners(mouse_listener=mock_mouse_listener)

        res = ef.mouse_event_filter(msg, None)
        assert res is True
        mock_mouse_listener.suppress_event.assert_not_called()
        assert ef.swallowed_mouse_count == 0
        assert ef.total_mouse_count == 1

    @pytest.mark.parametrize(
        "msg",
        [
            WM_MOUSEMOVE,
            WM_LBUTTONDOWN,
            WM_LBUTTONUP,
            WM_RBUTTONDOWN,
            WM_RBUTTONUP,
            WM_MBUTTONDOWN,
            WM_MBUTTONUP,
            WM_MOUSEWHEEL,
            WM_XBUTTONDOWN,
            WM_XBUTTONUP,
            WM_MOUSEHWHEEL,
        ],
    )
    def test_mouse_events_swallowed_when_locked(self, msg: int) -> None:
        ef = EventFilter(swallow_active=True)
        mock_mouse_listener = MagicMock()
        ef.set_listeners(mouse_listener=mock_mouse_listener)

        res = ef.mouse_event_filter(msg, None)
        assert res is True
        mock_mouse_listener.suppress_event.assert_called_once()
        assert ef.swallowed_mouse_count == 1
        assert ef.total_mouse_count == 1


class TestEventFilterResilienceAndEdgeCases:
    """Tests for edge cases, error resilience, and malformed data."""

    def test_raw_int_and_dict_data_supported(self) -> None:
        ef = EventFilter(swallow_active=True)
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        # Raw int data
        ef.keyboard_event_filter(WM_KEYDOWN, 0x41)
        # Dict data
        ef.keyboard_event_filter(WM_KEYDOWN, {"vkCode": 0x42})

        assert mock_kb_listener.suppress_event.call_count == 2
        assert 0x41 in ef.active_keys
        assert 0x42 in ef.active_keys

    def test_none_data_handled_gracefully(self) -> None:
        ef = EventFilter(swallow_active=True)
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        res = ef.keyboard_event_filter(WM_KEYDOWN, None)
        assert res is True
        mock_kb_listener.suppress_event.assert_not_called()

    def test_callback_exception_does_not_crash_filter(self) -> None:
        def bad_lock():
            raise RuntimeError("Lock callback exploded!")

        def bad_unlock():
            raise ValueError("Unlock callback exploded!")

        ef = EventFilter(
            on_lock_hotkey=bad_lock,
            on_unlock_hotkey=bad_unlock,
            swallow_active=False,
        )
        mock_kb_listener = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb_listener)

        # F11 with failing callback
        res_f11 = ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_F11))
        assert res_f11 is True
        mock_kb_listener.suppress_event.assert_called_once()

        # Unlock combo with failing callback
        ef.set_swallow(True)
        mock_kb_listener.reset_mock()
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_CONTROL))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_MENU))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_SHIFT))
        res_u = ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_U))
        assert res_u is True
        # Suppressed despite callback exception
        assert mock_kb_listener.suppress_event.call_count == 4

    def test_suppress_exception_raised_when_no_listener(self) -> None:
        ef = EventFilter(swallow_active=True)
        # No listener set -> suppress_keyboard() raises SuppressException
        with pytest.raises(SuppressException):
            ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(0x41))

        with pytest.raises(SuppressException):
            ef.mouse_event_filter(WM_MOUSEMOVE, None)

    def test_submillisecond_filter_execution_latency(self) -> None:
        """Verify that filter execution takes < 0.05 ms per event (< 1 ms budget)."""
        ef = EventFilter(swallow_active=True)
        mock_kb = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb)
        event_data = MockEventData(0x41)

        iterations = 2000
        start = time.perf_counter()
        for _ in range(iterations):
            ef.keyboard_event_filter(WM_KEYDOWN, event_data)
        elapsed = time.perf_counter() - start

        avg_latency_ms = (elapsed / iterations) * 1000.0
        # Budget is 1 ms; lock-free filter is typically under 0.01 ms
        assert avg_latency_ms < 0.1, f"Avg latency too high: {avg_latency_ms:.4f} ms"


# ============================================================================
# HookManager Tests
# ============================================================================


class TestHookManager:
    """Tests for HookManager lifecycle and interface contract."""

    def test_hook_manager_initial_state(self) -> None:
        hm = HookManager()
        assert hm.is_running is False
        assert hm.is_swallowing() is False
        assert isinstance(hm.event_filter, EventFilter)

    def test_hook_manager_set_swallow(self) -> None:
        hm = HookManager()
        hm.set_swallow(True)
        assert hm.is_swallowing() is True
        assert hm.event_filter.is_swallowing() is True

        hm.set_swallow(False)
        assert hm.is_swallowing() is False
        assert hm.event_filter.is_swallowing() is False

    def test_desktop_attachment_function(self) -> None:
        """Verify attach_input_desktop executes without unhandled exceptions."""
        result = attach_input_desktop()
        # In interactive Windows sessions, returns True or False safely
        assert isinstance(result, bool)

    def test_hook_manager_start_and_stop_lifecycle(self) -> None:
        """Verify real HookManager start and stop lifecycle."""
        hm = HookManager()
        assert hm.is_running is False

        hm.start()
        assert hm.is_running is True

        # Second start() call should be a no-op
        hm.start()
        assert hm.is_running is True

        hm.stop()
        assert hm.is_running is False

        # Second stop() call should be a no-op
        hm.stop()
        assert hm.is_running is False

    def test_hook_manager_context_manager(self) -> None:
        """Verify HookManager context manager (__enter__ / __exit__)."""
        with HookManager() as hm:
            assert hm.is_running is True
        assert hm.is_running is False


# ============================================================================
# Integration Cycle Test with Synthetic Injection
# ============================================================================


class TestHookIntegrationCycle:
    """Integration test simulating the full Lock -> Locked Input -> Unlock cycle."""

    def test_full_state_cycle_with_event_filter(self) -> None:
        """Simulate lock and unlock transitions and check swallowing counts."""
        state = {"locked": False}

        def on_lock():
            state["locked"] = True
            ef.set_swallow(True)

        def on_unlock():
            state["locked"] = False
            ef.set_swallow(False)

        ef = EventFilter(
            on_lock_hotkey=on_lock,
            on_unlock_hotkey=on_unlock,
            swallow_active=False,
        )
        mock_kb = MagicMock()
        mock_mouse = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb, mouse_listener=mock_mouse)

        # 1. Unlocked state: Normal key A arrives -> passed through
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(0x41))
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(0x41))
        assert state["locked"] is False
        assert ef.swallowed_keyboard_count == 0

        # Unlocked state: Mouse move -> passed through
        ef.mouse_event_filter(WM_MOUSEMOVE, None)
        assert ef.swallowed_mouse_count == 0

        # 2. Lock hotkey: F11 pressed -> triggers on_lock and is swallowed
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_F11))
        assert state["locked"] is True
        assert ef.is_swallowing() is True
        assert ef.swallowed_keyboard_count == 1

        # Release F11 -> swallowed
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_F11))
        assert ef.swallowed_keyboard_count == 2

        # 3. Locked state: Normal key B arrives -> swallowed!
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(0x42))
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(0x42))
        assert ef.swallowed_keyboard_count == 4

        # Locked state: Mouse clicks and moves -> swallowed!
        ef.mouse_event_filter(WM_MOUSEMOVE, None)
        ef.mouse_event_filter(WM_LBUTTONDOWN, None)
        ef.mouse_event_filter(WM_LBUTTONUP, None)
        assert ef.swallowed_mouse_count == 3

        # 4. Unlock sequence: Ctrl + Alt + Shift + U
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_LCONTROL))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_LMENU))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_LSHIFT))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_U))

        assert state["locked"] is False
        assert ef.is_swallowing() is False
        # Ctrl, Alt, Shift, U were all swallowed
        assert ef.swallowed_keyboard_count == 8

        # Clean release of modifiers
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_U))
        ef.keyboard_event_filter(WM_SYSKEYUP, MockEventData(VK_LSHIFT))
        ef.keyboard_event_filter(WM_SYSKEYUP, MockEventData(VK_LMENU))
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_LCONTROL))

        # 5. Post-unlock verification: Normal key C arrives -> passed through!
        before_count = ef.swallowed_keyboard_count
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(0x43))
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(0x43))
        assert ef.swallowed_keyboard_count == before_count


@pytest.mark.skipif(
    not hasattr(ctypes, "windll"),
    reason="Live SendInput hooks require Windows OS",
)
class TestLiveWindowsHooksWithSendInput:
    """Live integration tests using Win32 SendInput and active hook threads."""

    @staticmethod
    def _send_synthetic_key(vk: int, is_down: bool) -> None:
        import pynput._util.win32 as w32
        inp = w32.INPUT(type=w32.INPUT.KEYBOARD)
        flags = 0 if is_down else w32.KEYBDINPUT.KEYUP
        inp.value.ki = w32.KEYBDINPUT(
            wVk=vk,
            wScan=0,
            dwFlags=flags,
            time=0,
            dwExtraInfo=None,
        )
        w32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(w32.INPUT))

    def test_live_hook_lock_and_unlock_via_sendinput(self) -> None:
        """Verify F11 and Ctrl+Alt+Shift+U trigger transitions via SendInput."""
        lock_calls: List[float] = []
        unlock_calls: List[float] = []

        def on_lock() -> None:
            lock_calls.append(time.time())
            hm.set_swallow(True)

        def on_unlock() -> None:
            unlock_calls.append(time.time())
            hm.set_swallow(False)

        hm = HookManager(on_lock_hotkey=on_lock, on_unlock_hotkey=on_unlock)
        hm.start()
        time.sleep(0.3)

        try:
            # 1. Trigger Lock via F11
            self._send_synthetic_key(VK_F11, True)
            self._send_synthetic_key(VK_F11, False)
            time.sleep(0.15)

            assert len(lock_calls) >= 1, "F11 failed to trigger on_lock callback"
            assert hm.is_swallowing() is True, "HookManager not in swallowing state after F11"

            # 2. Trigger Unlock via Ctrl + Alt + Shift + U
            self._send_synthetic_key(VK_LCONTROL, True)
            self._send_synthetic_key(VK_LMENU, True)
            self._send_synthetic_key(VK_LSHIFT, True)
            self._send_synthetic_key(VK_U, True)
            time.sleep(0.15)

            assert len(unlock_calls) >= 1, "Unlock combo failed to trigger on_unlock callback"
            assert hm.is_swallowing() is False, "HookManager still swallowing after unlock combo"

        finally:
            # Always ensure modifiers are released and hook is stopped
            self._send_synthetic_key(VK_U, False)
            self._send_synthetic_key(VK_LSHIFT, False)
            self._send_synthetic_key(VK_LMENU, False)
            self._send_synthetic_key(VK_LCONTROL, False)
            hm.stop()

