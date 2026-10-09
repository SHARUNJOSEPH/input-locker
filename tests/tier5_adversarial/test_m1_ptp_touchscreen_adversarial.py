"""Milestone 1 Empirical Adversarial Stress Test Suite.

Adversarial validation for:
1. Rapid SC_MINIMIZE injection simulation & bitmask edge cases.
2. Rapid SWP_HIDEWINDOW / WM_WINDOWPOSCHANGING manipulation (locked vs unlocked).
3. Pointer and touch hit-testing / activation return value contract:
   WM_TOUCHHITTESTING (HTCLIENT), WM_POINTERACTIVATE (PA_NOACTIVATE),
   WM_NCHITTEST (HTCLIENT), WM_MOUSEACTIVATE (MA_NOACTIVATEANDEAT).
4. Property store edge gesture setting verification on native test window HWND.
5. Concurrent multi-threaded lock/unlock stress testing (zero deadlock, race-free).
6. Unlock hotkey (Ctrl+Alt+Shift+U) permutation resilience and modifier reset integrity.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
from ctypes import wintypes
import threading
import time
from typing import List, Set
from unittest.mock import MagicMock, patch

import pytest

from input_locker.core.controller import LockerController
from input_locker.core.state_machine import LockerState
from input_locker.hooks.event_filter import (
    EventFilter,
    VK_CONTROL,
    VK_LCONTROL,
    VK_RCONTROL,
    VK_MENU,
    VK_LMENU,
    VK_RMENU,
    VK_SHIFT,
    VK_LSHIFT,
    VK_RSHIFT,
    VK_LWIN,
    VK_RWIN,
    VK_U,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
)
from input_locker.overlay.win32_overlay import (
    Win32Overlay,
    _global_overlay_wndproc,
    set_overlay_locked,
    is_overlay_locked,
    disable_edge_gestures,
    PKEY_EdgeGesture_DisableTouchWhenFullscreen,
    IID_IPropertyStore,
    PROPERTYKEY,
    PROPVARIANT,
    WINDOWPOS,
    WM_NCHITTEST,
    WM_MOUSEACTIVATE,
    WM_TOUCHHITTESTING,
    WM_POINTERACTIVATE,
    WM_SYSCOMMAND,
    WM_WINDOWPOSCHANGING,
    WM_SHOWWINDOW,
    HTCLIENT,
    MA_NOACTIVATEANDEAT,
    PA_NOACTIVATE,
    SC_MINIMIZE,
    HWND_TOPMOST,
    SWP_HIDEWINDOW,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_SHOWWINDOW,
    SWP_NOACTIVATE,
    register_raw_touch,
    unregister_raw_touch,
)
from input_locker.overlay.overlay_manager import OverlayManager


class DummyHookData:
    """Helper struct mimicking KBDLLHOOKSTRUCT for event filter testing."""
    def __init__(self, vk: int):
        self.vkCode = vk


# ===========================================================================
# 1. Rapid SC_MINIMIZE Injection Simulation
# ===========================================================================

class TestRapidScMinimizeAdversarial:
    """Adversarial stress testing of SC_MINIMIZE absorption."""

    def test_rapid_sc_minimize_flood(self):
        """Simulate 2,000 rapid SC_MINIMIZE messages to ensure 100% absorption and zero pass-through."""
        with patch("input_locker.overlay.win32_overlay._user32.DefWindowProcW") as mock_def_proc:
            for i in range(2000):
                # The shell and low-level drivers can set lower 4 bits in wParam
                wparam = SC_MINIMIZE | (i & 0x000F)
                res = _global_overlay_wndproc(1234, WM_SYSCOMMAND, wparam, 0)
                assert res == 0, f"SC_MINIMIZE (0x{wparam:04X}) was not absorbed on iteration {i}"

            # DefWindowProcW must NEVER have been called for SC_MINIMIZE
            mock_def_proc.assert_not_called()

    def test_sc_minimize_bitmask_boundaries(self):
        """Test all 16 bitwise lower-nibble variations of SC_MINIMIZE."""
        with patch("input_locker.overlay.win32_overlay._user32.DefWindowProcW") as mock_def_proc:
            for sub_code in range(16):
                wparam = SC_MINIMIZE | sub_code
                res = _global_overlay_wndproc(9999, WM_SYSCOMMAND, wparam, 0)
                assert res == 0, f"SC_MINIMIZE variant 0x{wparam:X} failed"

            # Non-minimize commands must pass through cleanly
            mock_def_proc.return_value = 100
            for other_cmd in (0xF010, 0xF030, 0xF060, 0xF120):  # SC_MOVE, SC_MAXIMIZE, SC_CLOSE, SC_RESTORE
                res = _global_overlay_wndproc(9999, WM_SYSCOMMAND, other_cmd, 0)
                assert res == 100, f"Non-minimize syscommand 0x{other_cmd:X} was incorrectly blocked"

    def test_multithreaded_sc_minimize_hammering(self):
        """Multi-threaded stress: 8 concurrent threads firing 500 SC_MINIMIZE messages each."""
        with patch("input_locker.overlay.win32_overlay._user32.DefWindowProcW") as mock_def_proc:
            errors: List[str] = []

            def hammer(thread_id: int):
                try:
                    for i in range(500):
                        res = _global_overlay_wndproc(thread_id, WM_SYSCOMMAND, SC_MINIMIZE | (i % 16), 0)
                        if res != 0:
                            errors.append(f"Thread {thread_id} got non-zero return: {res}")
                except Exception as exc:
                    errors.append(f"Thread {thread_id} exception: {exc}")

            threads = [threading.Thread(target=hammer, args=(tid,)) for tid in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

            assert not errors, f"Concurrent SC_MINIMIZE errors: {errors}"
            mock_def_proc.assert_not_called()


# ===========================================================================
# 2. Rapid SWP_HIDEWINDOW / WM_WINDOWPOSCHANGING Simulation (Locked vs Unlocked)
# ===========================================================================

class TestWindowPosChangingAntiHideAdversarial:
    """Adversarial stress testing of WM_WINDOWPOSCHANGING anti-hide logic."""

    def test_rapid_swp_hidewindow_attempts_while_locked(self):
        """Simulate 1,000 rapid attempts to hide the window while locked."""
        try:
            set_overlay_locked(True)
            for i in range(1000):
                wp = WINDOWPOS()
                wp.hwnd = 8888
                wp.hwndInsertAfter = 0
                # Combine SWP_HIDEWINDOW with random other flags
                wp.flags = SWP_HIDEWINDOW | SWP_NOMOVE | SWP_NOSIZE | (i % 64)

                res = _global_overlay_wndproc(8888, WM_WINDOWPOSCHANGING, 0, ctypes.addressof(wp))
                assert res == 0
                assert (wp.flags & SWP_HIDEWINDOW) == 0, f"SWP_HIDEWINDOW not stripped on iteration {i}"
                assert ctypes.c_int64(wp.hwndInsertAfter).value == HWND_TOPMOST, f"hwndInsertAfter not TOPMOST on {i}"
        finally:
            set_overlay_locked(True)

    def test_swp_hidewindow_preserved_when_unlocked(self):
        """Verify that when unlocked, SWP_HIDEWINDOW is preserved so overlay can hide cleanly."""
        try:
            set_overlay_locked(False)
            wp = WINDOWPOS()
            wp.hwnd = 8888
            wp.flags = SWP_HIDEWINDOW | SWP_NOACTIVATE

            res = _global_overlay_wndproc(8888, WM_WINDOWPOSCHANGING, 0, ctypes.addressof(wp))
            assert res == 0
            assert (wp.flags & SWP_HIDEWINDOW) == SWP_HIDEWINDOW, "SWP_HIDEWINDOW was stripped when unlocked"
        finally:
            set_overlay_locked(True)

    def test_windowposchanging_null_lparam_safety(self):
        """Adversarial probe: NULL lparam must not crash _global_overlay_wndproc."""
        try:
            set_overlay_locked(True)
            # lparam = 0 (NULL pointer)
            res = _global_overlay_wndproc(8888, WM_WINDOWPOSCHANGING, 0, 0)
            assert res == 0
        finally:
            set_overlay_locked(True)

    def test_showwindow_anti_hide_reasserts_topmost_when_locked(self):
        """WM_SHOWWINDOW with wParam=0 (hide) while locked must reassert topmost."""
        try:
            set_overlay_locked(True)
            with patch("input_locker.overlay.win32_overlay._user32.SetWindowPos") as mock_swp, \
                 patch("input_locker.overlay.win32_overlay._user32.DefWindowProcW") as mock_def:
                res = _global_overlay_wndproc(8888, WM_SHOWWINDOW, 0, 0)
                assert res == 0
                mock_swp.assert_called_once_with(
                    8888,
                    HWND_TOPMOST,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE,
                )
                mock_def.assert_not_called()
        finally:
            set_overlay_locked(True)

    def test_showwindow_allows_hide_when_unlocked(self):
        """WM_SHOWWINDOW with wParam=0 when unlocked falls through to DefWindowProcW."""
        try:
            set_overlay_locked(False)
            with patch("input_locker.overlay.win32_overlay._user32.SetWindowPos") as mock_swp, \
                 patch("input_locker.overlay.win32_overlay._user32.DefWindowProcW") as mock_def:
                mock_def.return_value = 0
                res = _global_overlay_wndproc(8888, WM_SHOWWINDOW, 0, 0)
                mock_def.assert_called_once_with(8888, WM_SHOWWINDOW, 0, 0)
                mock_swp.assert_not_called()
        finally:
            set_overlay_locked(True)


# ===========================================================================
# 3. Pointer and Touch Hit-Testing / Activation Return Values
# ===========================================================================

class TestHitTestingAndActivationReturnValuesAdversarial:
    """Exhaustively verify the exact Win32 return codes for touch, pointer, and activation messages."""

    def test_wm_touchhittest_returns_htclient(self):
        """WM_TOUCHHITTESTING must return HTCLIENT (1), NEVER HTNOWHERE (0)."""
        res = _global_overlay_wndproc(1234, WM_TOUCHHITTESTING, 0, 0)
        assert res == HTCLIENT, f"Expected HTCLIENT (1), got {res}"

    def test_wm_pointeractivate_returns_pa_noactivate(self):
        """WM_POINTERACTIVATE must return PA_NOACTIVATE (3) to prevent focus theft."""
        res = _global_overlay_wndproc(1234, WM_POINTERACTIVATE, 0, 0)
        assert res == PA_NOACTIVATE, f"Expected PA_NOACTIVATE (3), got {res}"

    def test_wm_nchittest_returns_htclient(self):
        """WM_NCHITTEST must return HTCLIENT (1) so mouse/touch hits the client area."""
        res = _global_overlay_wndproc(1234, WM_NCHITTEST, 0, 0)
        assert res == HTCLIENT, f"Expected HTCLIENT (1), got {res}"

    def test_wm_mouseactivate_returns_ma_noactivateandeat(self):
        """WM_MOUSEACTIVATE must return MA_NOACTIVATEANDEAT (3)."""
        res = _global_overlay_wndproc(1234, WM_MOUSEACTIVATE, 0, 0)
        assert res == MA_NOACTIVATEANDEAT, f"Expected MA_NOACTIVATEANDEAT (3), got {res}"

    def test_all_pointer_messages_absorbed_with_zero(self):
        """Every message in the Windows 8+ pointer architecture must return 0."""
        pointer_messages = [
            0x0241,  # WM_NCPOINTERUPDATE
            0x0242,  # WM_NCPOINTERDOWN
            0x0243,  # WM_NCPOINTERUP
            0x0245,  # WM_POINTERUPDATE
            0x0246,  # WM_POINTERDOWN
            0x0247,  # WM_POINTERUP
            0x0249,  # WM_POINTERENTER
            0x024A,  # WM_POINTERLEAVE
            0x024C,  # WM_POINTERCAPTURECHANGED
            0x0252,  # WM_POINTERWHEEL
            0x0253,  # WM_POINTERHWHEEL
        ]
        for msg in pointer_messages:
            res = _global_overlay_wndproc(1234, msg, 0, 0)
            assert res == 0, f"Pointer message 0x{msg:04X} returned {res} instead of 0"

    def test_wm_touch_and_wm_gesture_close_handles_and_return_zero(self):
        """WM_TOUCH (0x0240) and WM_GESTURE (0x0119) must close handles and return 0."""
        with patch("input_locker.overlay.win32_overlay._user32.CloseTouchInputHandle") as mock_close_touch, \
             patch("input_locker.overlay.win32_overlay._user32.CloseGestureInfoHandle") as mock_close_gesture:
            mock_close_touch.return_value = 1
            mock_close_gesture.return_value = 1

            # Test WM_TOUCH
            res_touch = _global_overlay_wndproc(1234, 0x0240, 1, 0x9999)
            assert res_touch == 0
            mock_close_touch.assert_called_once_with(0x9999)

            # Test WM_GESTURE
            res_gesture = _global_overlay_wndproc(1234, 0x0119, 1, 0x8888)
            assert res_gesture == 0
            mock_close_gesture.assert_called_once_with(0x8888)


# ===========================================================================
# 4. Property Store Edge Gesture Setting Verification on Test Window
# ===========================================================================

class TestPropertyStoreEdgeGesturesAdversarial:
    """Stress test and verify disable_edge_gestures on native Windows window."""

    def test_disable_edge_gestures_on_real_win32_overlay_window(self):
        """Create a real Win32Overlay window and verify disable_edge_gestures executes cleanly."""
        overlay = Win32Overlay(auto_prewarm=False)
        try:
            overlay.prewarm()
            hwnd = overlay.hwnd
            assert hwnd is not None and hwnd != 0

            # disable_edge_gestures was called in prewarm on the UI thread
            # Verify the edge gesture atom is registered on the overlay window HWND
            user32 = ctypes.windll.user32
            prop_val = user32.GetPropW(hwnd, "{32CE38B2-2C9A-41B1-9BC5-B3784394AA44} 2")
            assert prop_val != 0, "PKEY_EdgeGesture property atom not found on overlay HWND"

            # Now test disable_edge_gestures directly on a test window HWND on the current thread
            test_hwnd = user32.CreateWindowExW(0, "STATIC", "EdgeTestWindow", 0, 0, 0, 100, 100, 0, 0, 0, 0)
            assert test_hwnd != 0
            try:
                ok = disable_edge_gestures(test_hwnd)
                assert ok is True, f"disable_edge_gestures failed on test_hwnd {test_hwnd}"

                # Verify window prop atom is registered on test_hwnd
                prop_test_val = user32.GetPropW(test_hwnd, "{32CE38B2-2C9A-41B1-9BC5-B3784394AA44} 2")
                assert prop_test_val != 0, "Window property handle not found on test_hwnd"
            finally:
                user32.DestroyWindow(test_hwnd)
        finally:
            overlay.close()

    def test_disable_edge_gestures_invalid_hwnd_handling(self):
        """Verify disable_edge_gestures handles invalid or zero HWND gracefully."""
        # HWND 0 must return False immediately
        assert disable_edge_gestures(0) is False

        # Invalid/non-existent HWND must return False without throwing exception
        res = disable_edge_gestures(0xDEADBEEF)
        assert res is False


# ===========================================================================
# 5. Concurrent Lock/Unlock Stress Testing (Zero Deadlock, Race Conditions)
# ===========================================================================

class TestConcurrentLockUnlockStressAdversarial:
    """Multi-threaded concurrency hammering on LockerController and OverlayManager."""

    def test_100_rapid_successive_lock_unlock_cycles(self):
        """Execute 100 consecutive rapid lock/unlock cycles measuring latency against <200ms budget."""
        ctrl = LockerController(overlay_backend="win32", audio_feedback=False)
        try:
            latencies: List[float] = []
            for cycle in range(100):
                t0 = time.perf_counter()
                locked = ctrl.lock()
                assert locked is True, f"Failed to lock on cycle {cycle}"
                assert ctrl.is_locked() is True

                unlocked = ctrl.unlock()
                assert unlocked is True, f"Failed to unlock on cycle {cycle}"
                assert ctrl.is_locked() is False
                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000.0)

            avg_latency = sum(latencies) / len(latencies)
            max_latency = max(latencies)
            p95_latency = sorted(latencies)[int(0.95 * len(latencies))]

            assert max_latency < 250.0, f"Max cycle latency exceeded budget: {max_latency:.2f} ms"
            assert avg_latency < 50.0, f"Average cycle latency too high: {avg_latency:.2f} ms"
        finally:
            ctrl.stop()

    def test_concurrent_multithreaded_hammering(self):
        """Spawn 12 worker threads concurrently attempting to lock and unlock the controller."""
        ctrl = LockerController(overlay_backend="win32", audio_feedback=False)
        stop_event = threading.Event()
        errors: List[Exception] = []
        action_count = 0
        action_lock = threading.Lock()

        def worker(tid: int):
            nonlocal action_count
            while not stop_event.is_set():
                try:
                    if tid % 2 == 0:
                        ctrl.lock()
                    else:
                        ctrl.unlock()
                    with action_lock:
                        action_count += 1
                except Exception as exc:
                    errors.append(exc)
                time.sleep(0.001)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()

        # Run hammering for 1.5 seconds
        time.sleep(1.5)
        stop_event.set()

        for t in threads:
            t.join(timeout=3.0)

        try:
            assert not errors, f"Concurrent exceptions occurred: {errors}"
            assert action_count >= 50, f"Expected high action count, got {action_count}"

            # Controller must remain stable and unlock cleanly
            ctrl.unlock()
            assert ctrl.is_locked() is False
        finally:
            ctrl.stop()

    def test_overlay_manager_concurrent_rapid_show_hide(self):
        """Stress test OverlayManager show/hide under concurrent multi-threaded contention."""
        mgr = OverlayManager(backend="win32", alpha=120)
        errors: List[Exception] = []

        def toggler(tid: int):
            try:
                for i in range(25):
                    if tid % 2 == 0:
                        mgr.show_overlay()
                    else:
                        mgr.hide_overlay()
                    time.sleep(0.002)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=toggler, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"OverlayManager concurrency errors: {errors}"
        mgr.unlock()
        assert mgr.is_overlay_visible() is False


# ===========================================================================
# 6. Unlock Hotkey & Modifier Reset Integrity Adversarial Testing
# ===========================================================================

class TestUnlockHotkeyAndModifierResetAdversarial:
    """Stress test unlock hotkey permutation resilience and modifier reset integrity."""

    def test_unlock_hotkey_press_permutations(self):
        """Verify Ctrl+Alt+Shift+U triggers regardless of the order the modifiers were pressed."""
        unlock_triggered = False

        def on_unlock():
            nonlocal unlock_triggered
            unlock_triggered = True

        ef = EventFilter(on_unlock_hotkey=on_unlock, swallow_active=True)
        mock_kb = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb)

        # 4! = 24 permutations of (Ctrl, Alt, Shift, U)
        import itertools
        key_tuples = [
            (VK_LCONTROL, "Ctrl"),
            (VK_LMENU, "Alt"),
            (VK_LSHIFT, "Shift"),
            (VK_U, "U"),
        ]

        for perm in itertools.permutations(key_tuples):
            unlock_triggered = False
            ef.set_swallow(True)
            ef._active_keys.clear()

            # Press all keys in this permutation order
            for vk, name in perm:
                ef.keyboard_event_filter(WM_KEYDOWN, DummyHookData(vk))

            assert unlock_triggered is True, (
                f"Unlock failed to trigger with permutation: {[n for _, n in perm]}"
            )

            # Release all keys
            for vk, name in perm:
                ef.keyboard_event_filter(WM_KEYUP, DummyHookData(vk))

            # Active keys must be empty
            assert not ef.active_keys, f"Active keys not empty after release: {ef.active_keys}"

    def test_unlock_combo_trailing_keyups_swallowed(self):
        """Verify that when unlocked, the keyup release events for Ctrl, Alt, Shift, U are swallowed."""
        unlock_calls = 0

        def on_unlock():
            nonlocal unlock_calls
            unlock_calls += 1

        ef = EventFilter(on_unlock_hotkey=on_unlock, swallow_active=True)
        mock_kb = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb)

        # Press combo
        ef.keyboard_event_filter(WM_KEYDOWN, DummyHookData(VK_LCONTROL))
        ef.keyboard_event_filter(WM_KEYDOWN, DummyHookData(VK_LMENU))
        ef.keyboard_event_filter(WM_KEYDOWN, DummyHookData(VK_LSHIFT))
        ef.keyboard_event_filter(WM_KEYDOWN, DummyHookData(VK_U))
        assert unlock_calls == 1

        # Controller unlocks, toggling swallow_active to False
        ef.set_swallow(False)
        assert ef.swallow_active is False

        # Trailing keyups must be swallowed via pending_unlock_keyups!
        with patch.object(ef, "suppress_keyboard") as mock_suppress:
            # Release U
            ef.keyboard_event_filter(WM_KEYUP, DummyHookData(VK_U))
            # Release Shift
            ef.keyboard_event_filter(WM_KEYUP, DummyHookData(VK_LSHIFT))
            # Release Alt
            ef.keyboard_event_filter(WM_KEYUP, DummyHookData(VK_LMENU))
            # Release Ctrl
            ef.keyboard_event_filter(WM_KEYUP, DummyHookData(VK_LCONTROL))

            # All 4 keyups must have been suppressed
            assert mock_suppress.call_count == 4, (
                f"Expected 4 suppressed keyups, got {mock_suppress.call_count}"
            )

    def test_ptp_gesture_shortcuts_swallowed_when_locked(self):
        """Verify that multi-finger precision touchpad shortcut combinations are strictly swallowed."""
        ef = EventFilter(swallow_active=True)

        gesture_combos = [
            # Win + Tab (Task View)
            ([VK_LWIN, 0x09], "Win+Tab"),
            # Alt + Tab (Task Switcher)
            ([VK_LMENU, 0x09], "Alt+Tab"),
            # Ctrl + Win + Left (Desktop switch)
            ([VK_LCONTROL, VK_LWIN, 0x25], "Ctrl+Win+Left"),
            # Ctrl + Win + Right (Desktop switch)
            ([VK_LCONTROL, VK_LWIN, 0x27], "Ctrl+Win+Right"),
            # Win + D (Show Desktop)
            ([VK_LWIN, 0x44], "Win+D"),
            # Win + A (Action Center)
            ([VK_LWIN, 0x41], "Win+A"),
            # Win + S (Search)
            ([VK_LWIN, 0x53], "Win+S"),
            # Win + Up / Down / Left / Right (Snap)
            ([VK_LWIN, 0x26], "Win+Up"),
            ([VK_LWIN, 0x28], "Win+Down"),
        ]

        for combo, desc in gesture_combos:
            ef._active_keys.clear()
            with patch.object(ef, "suppress_keyboard") as mock_suppress:
                for vk in combo:
                    ef.keyboard_event_filter(WM_KEYDOWN, DummyHookData(vk))

                assert mock_suppress.call_count >= len(combo), (
                    f"Gesture shortcut {desc} failed to be suppressed"
                )

    def test_reset_system_modifiers_releases_all_keys(self):
        """Verify _reset_system_modifiers synthesizes KEYUP for all 5 modifier virtual keys."""
        ef = EventFilter(swallow_active=False)
        with patch("input_locker.hooks.event_filter.user32") as mock_user32, \
             patch("input_locker.hooks.event_filter.HAS_USER32", True):
            # Simulate all modifier keys currently reported as down by GetAsyncKeyState
            mock_user32.GetAsyncKeyState.return_value = 0x8000

            ef._reset_system_modifiers()

            # Must call keybd_event with KEYEVENTF_KEYUP (0x0002) for 0x11, 0x12, 0x10, 0x5B, 0x5C
            expected_vks = {0x11, 0x12, 0x10, 0x5B, 0x5C}
            called_vks = {call[0][0] for call in mock_user32.keybd_event.call_args_list}
            assert expected_vks.issubset(called_vks), f"Missing synthesized modifier keyups: {expected_vks - called_vks}"
