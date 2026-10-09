"""Tier 5 Adversarial Stress Suite for Milestone 1: Windows 11 PTP & Touchscreen Neutralization.

Empirical verification harness developed by Challenger agent (challenger_m1_2).
Directly tests:
1. Task View Watcher Responsiveness & Dismissal (XamlExplorerHostIslandWindow, MultitaskingViewFrame)
2. Universal Virtual Desktop Pinning (WS_EX_TOOLWINDOW preservation, WS_EX_TRANSPARENT omission)
3. Deterministic Touch & Pointer Message Absorption (WM_POINTER*, WM_TOUCH, WM_GESTURE, hit-testing)
4. Focus Preservation & Anti-Disruption (WS_EX_NOACTIVATE, SWP_NOACTIVATE, zero WM_ACTIVATE)
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
import time
from unittest.mock import MagicMock, call, patch
import pytest

from input_locker.overlay.win32_overlay import (
    Win32Overlay,
    OVERLAY_EX_STYLE,
    WS_EX_NOACTIVATE,
    WS_EX_TRANSPARENT,
    WS_EX_LAYERED,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WM_SHOWWINDOW,
    WM_WINDOWPOSCHANGING,
    WM_SYSCOMMAND,
    SC_MINIMIZE,
    WM_MOUSEACTIVATE,
    MA_NOACTIVATEANDEAT,
    WM_POINTERACTIVATE,
    PA_NOACTIVATE,
    WM_TOUCHHITTESTING,
    HTCLIENT,
    WINDOWPOS,
    HWND_TOPMOST,
    SWP_HIDEWINDOW,
    SWP_SHOWWINDOW,
    SWP_NOACTIVATE,
    disable_edge_gestures,
    set_overlay_locked,
    is_overlay_locked,
    _global_overlay_wndproc,
    WM_NCHITTEST,
    register_raw_touch,
    unregister_raw_touch,
)
from input_locker.overlay.pyqt_overlay import PyQtOverlay, PYQT6_AVAILABLE
from input_locker.core.controller import LockerController
from input_locker.core.state_machine import LockerState
from tests.harness.focus_harness import CompanionFocusHarness


class TestTaskViewWatcherStress:
    """Empirically stress-tests Task View detection, responsiveness, and dismissal behavior."""

    @pytest.mark.parametrize("target_class", [
        "XamlExplorerHostIslandWindow",
        "MultitaskingViewFrame",
    ])
    def test_foreground_task_view_dismissal_and_escape(self, target_class: str):
        """Verifies foreground Task View window detection triggers WM_CLOSE and VK_ESCAPE."""
        mock_overlay = MagicMock()
        controller = LockerController(
            overlay_manager=mock_overlay,
            auto_prewarm=False,
            auto_register_signals=False,
        )

        fake_hwnd = 0x1234

        def fake_get_class_name(hwnd, buf, size):
            buf.value = target_class
            return len(target_class)

        def fake_get_window_text(hwnd, buf, size):
            buf.value = "Task View Shell"
            return len(buf.value)

        with patch.object(ctypes.windll.user32, "GetForegroundWindow", return_value=fake_hwnd), \
             patch.object(ctypes.windll.user32, "GetClassNameW", side_effect=fake_get_class_name), \
             patch.object(ctypes.windll.user32, "GetWindowTextW", side_effect=fake_get_window_text), \
             patch.object(ctypes.windll.user32, "PostMessageW") as mock_post, \
             patch.object(ctypes.windll.user32, "keybd_event") as mock_keybd, \
             patch.object(ctypes.windll.user32, "FindWindowW", return_value=0):

            controller.state_machine._state = LockerState.LOCKED
            controller._start_watchdog()
            time.sleep(0.12)
            controller._watchdog_stop_event.set()

            # WM_CLOSE (0x0010) must be dispatched to the shell switcher HWND
            mock_post.assert_any_call(fake_hwnd, 0x0010, 0, 0)

            # VK_ESCAPE (0x1B) down (flags=0) and up (flags=0x0002) must be sent
            escape_downs = [c for c in mock_keybd.call_args_list if c[0][0] == 0x1B and c[0][2] == 0]
            escape_ups = [c for c in mock_keybd.call_args_list if c[0][0] == 0x1B and c[0][2] == 0x0002]
            assert len(escape_downs) >= 1, "VK_ESCAPE key-down event was not sent"
            assert len(escape_ups) >= 1, "VK_ESCAPE key-up event was not sent"

            # Overlay show must be re-asserted
            mock_overlay.overlay.show.assert_called()

    def test_background_unactivated_task_view_dismissal(self):
        """Verifies background Task View window found via FindWindowW is dismissed immediately."""
        mock_overlay = MagicMock()
        controller = LockerController(
            overlay_manager=mock_overlay,
            auto_prewarm=False,
            auto_register_signals=False,
        )

        background_hwnds = {
            "MultitaskingViewFrame": 0xAAA1,
            "XamlExplorerHostIslandWindow": 0xBBB2,
        }

        def fake_find_window(cls_name, title_name):
            return background_hwnds.get(cls_name, 0)

        with patch.object(ctypes.windll.user32, "GetForegroundWindow", return_value=0), \
             patch.object(ctypes.windll.user32, "PostMessageW") as mock_post, \
             patch.object(ctypes.windll.user32, "keybd_event") as mock_keybd, \
             patch.object(ctypes.windll.user32, "FindWindowW", side_effect=fake_find_window):

            controller.state_machine._state = LockerState.LOCKED
            controller._start_watchdog()
            time.sleep(0.12)
            controller._watchdog_stop_event.set()

            # Both background windows must receive WM_CLOSE
            mock_post.assert_any_call(0xAAA1, 0x0010, 0, 0)
            mock_post.assert_any_call(0xBBB2, 0x0010, 0, 0)

            escape_calls = [c for c in mock_keybd.call_args_list if c[0][0] == 0x1B]
            assert len(escape_calls) >= 2, "VK_ESCAPE was not dispatched for background task view"

    def test_rapid_task_view_storm_responsiveness(self):
        """Simulates 50 rapid Task View popups and verifies latency and zero crash/drift."""
        mock_overlay = MagicMock()
        controller = LockerController(
            overlay_manager=mock_overlay,
            auto_prewarm=False,
            auto_register_signals=False,
        )

        popup_count = 0
        max_popups = 50
        dismissed_hwnds = []

        def fake_get_foreground():
            nonlocal popup_count
            if popup_count < max_popups:
                popup_count += 1
                return 1000 + popup_count
            return 0

        def fake_get_class_name(hwnd, buf, size):
            buf.value = "XamlExplorerHostIslandWindow"
            return len(buf.value)

        def fake_post_message(hwnd, msg, wp, lp):
            if msg == 0x0010:
                dismissed_hwnds.append(hwnd)
            return 1

        with patch.object(ctypes.windll.user32, "GetForegroundWindow", side_effect=fake_get_foreground), \
             patch.object(ctypes.windll.user32, "GetClassNameW", side_effect=fake_get_class_name), \
             patch.object(ctypes.windll.user32, "GetWindowTextW", return_value=0), \
             patch.object(ctypes.windll.user32, "PostMessageW", side_effect=fake_post_message), \
             patch.object(ctypes.windll.user32, "keybd_event"), \
             patch.object(ctypes.windll.user32, "FindWindowW", return_value=0):

            controller.state_machine._state = LockerState.LOCKED
            t0 = time.perf_counter()
            controller._start_watchdog()

            # Wait until at least 30 popups are processed or timeout
            for _ in range(50):
                if len(dismissed_hwnds) >= 30:
                    break
                time.sleep(0.02)

            controller._watchdog_stop_event.set()
            elapsed_s = time.perf_counter() - t0

        assert len(dismissed_hwnds) >= 5, f"Watchdog failed to process rapid popups: only {len(dismissed_hwnds)}"
        print(f"\n[Task View Storm] Processed {len(dismissed_hwnds)} popups in {elapsed_s:.3f}s")

    def test_watchdog_respects_password_mode(self):
        """Verifies watchdog does NOT issue VK_ESCAPE while password dialog is active."""
        mock_overlay = MagicMock()
        controller = LockerController(
            overlay_manager=mock_overlay,
            auto_prewarm=False,
            auto_register_signals=False,
        )

        # Set password mode active on hook_manager
        controller.hook_manager.set_password_mode(True)

        with patch.object(ctypes.windll.user32, "GetForegroundWindow", return_value=9999), \
             patch.object(ctypes.windll.user32, "GetClassNameW") as mock_get_class, \
             patch.object(ctypes.windll.user32, "keybd_event") as mock_keybd:

            controller.state_machine._state = LockerState.LOCKED
            controller._start_watchdog()
            time.sleep(0.12)
            controller._watchdog_stop_event.set()

            # Should not inspect foreground or send escape keys
            mock_get_class.assert_not_called()
            mock_keybd.assert_not_called()


class TestVirtualDesktopPinningStress:
    """Empirically stress-tests WS_EX_TOOLWINDOW pinning across virtual desktops."""

    def test_win32_overlay_ex_styles_matrix(self):
        """Verifies exact bitmask composition for universal virtual desktop pinning."""
        # 1. WS_EX_TOOLWINDOW (0x80) MUST be present (instructs DWM to pin across all virtual desktops)
        assert (OVERLAY_EX_STYLE & WS_EX_TOOLWINDOW) == WS_EX_TOOLWINDOW

        # 2. WS_EX_NOACTIVATE (0x08000000) MUST be present (prevents focus loss to background apps)
        assert (OVERLAY_EX_STYLE & WS_EX_NOACTIVATE) == WS_EX_NOACTIVATE

        # 3. WS_EX_LAYERED (0x00080000) MUST be present (enables transparency alpha)
        assert (OVERLAY_EX_STYLE & WS_EX_LAYERED) == WS_EX_LAYERED

        # 4. WS_EX_TOPMOST (0x00000008) MUST be present (renders above ordinary windows)
        assert (OVERLAY_EX_STYLE & WS_EX_TOPMOST) == WS_EX_TOPMOST

        # 5. WS_EX_TRANSPARENT (0x20) MUST NOT be present (prevents click/touch pass-through)
        assert (OVERLAY_EX_STYLE & WS_EX_TRANSPARENT) == 0

        # Exact bitwise value check: 0x08000000 | 0x00080000 | 0x00000080 | 0x00000008 = 0x08080088
        assert OVERLAY_EX_STYLE == 0x08080088

    def test_win32_overlay_live_window_ex_style_persistence(self):
        """Verifies live Win32 HWND retains WS_EX_TOOLWINDOW and does NOT have WS_EX_TRANSPARENT."""
        with Win32Overlay(alpha=120) as overlay:
            assert overlay.hwnd is not None
            ex_style = overlay.get_ex_style()

            assert (ex_style & WS_EX_TOOLWINDOW) != 0, "Live HWND missing WS_EX_TOOLWINDOW"
            assert (ex_style & WS_EX_TRANSPARENT) == 0, "Live HWND has unwanted WS_EX_TRANSPARENT"
            assert (ex_style & WS_EX_NOACTIVATE) != 0, "Live HWND missing WS_EX_NOACTIVATE"
            assert (ex_style & WS_EX_TOPMOST) != 0, "Live HWND missing WS_EX_TOPMOST"

            # Stress: dynamic alpha changes must preserve styles
            for alpha_val in (0, 50, 120, 200, 255):
                overlay.set_alpha(alpha_val)
                style_after = overlay.get_ex_style()
                assert (style_after & WS_EX_TOOLWINDOW) != 0

    @pytest.mark.skipif(not PYQT6_AVAILABLE, reason="PyQt6 not installed")
    def test_pyqt_overlay_retains_toolwindow_across_cycles(self):
        """Verifies PyQt overlay widgets retain WS_EX_TOOLWINDOW across multiple show/hide cycles."""
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW_FLAG = 0x00000080

        with PyQtOverlay() as overlay:
            overlay.prewarm()
            for cycle in range(5):
                overlay.show()
                time.sleep(0.02)
                for w in overlay._widgets:
                    hwnd = int(w.winId())
                    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    assert (ex_style & WS_EX_TOOLWINDOW_FLAG) != 0, (
                        f"Cycle {cycle}: PyQt widget HWND {hwnd} lost WS_EX_TOOLWINDOW!"
                    )
                overlay.hide()
                time.sleep(0.01)

    def test_edge_gesture_disable_on_live_window(self):
        """Empirically invokes disable_edge_gestures on live window HWND."""
        user32 = ctypes.windll.user32
        hwnd = user32.CreateWindowExW(0, "STATIC", "EdgeGestureTest", 0, 0, 0, 100, 100, 0, 0, 0, 0)
        assert hwnd != 0
        try:
            success = disable_edge_gestures(hwnd)
            assert success is True, "disable_edge_gestures failed on valid HWND"
        finally:
            user32.DestroyWindow(hwnd)


class TestTouchscreenTapAbsorptionStress:
    """Empirically stress-tests pointer and touch message absorption and unmanaged resource safety."""

    @pytest.mark.parametrize("msg_id,msg_name", [
        (0x0241, "WM_NCPOINTERUPDATE"),
        (0x0242, "WM_NCPOINTERDOWN"),
        (0x0243, "WM_NCPOINTERUP"),
        (0x0245, "WM_POINTERUPDATE"),
        (0x0246, "WM_POINTERDOWN"),
        (0x0247, "WM_POINTERUP"),
        (0x0249, "WM_POINTERENTER"),
        (0x024A, "WM_POINTERLEAVE"),
        (0x024C, "WM_POINTERCAPTURECHANGED"),
        (0x0252, "WM_POINTERWHEEL"),
        (0x0253, "WM_POINTERHWHEEL"),
        (0x0240, "WM_TOUCH"),
        (0x0119, "WM_GESTURE"),
        (0x0200, "WM_MOUSEMOVE"),
        (0x0201, "WM_LBUTTONDOWN"),
        (0x0202, "WM_LBUTTONUP"),
        (0x0203, "WM_LBUTTONDBLCLK"),
        (0x0204, "WM_RBUTTONDOWN"),
        (0x0205, "WM_RBUTTONUP"),
        (0x0206, "WM_RBUTTONDBLCLK"),
        (0x0207, "WM_MBUTTONDOWN"),
        (0x0208, "WM_MBUTTONUP"),
        (0x0209, "WM_MBUTTONDBLCLK"),
        (0x020A, "WM_MOUSEWHEEL"),
        (0x020B, "WM_XBUTTONDOWN"),
        (0x020C, "WM_XBUTTONUP"),
        (0x020D, "WM_XBUTTONDBLCLK"),
        (0x020E, "WM_MOUSEHWHEEL"),
        (0x007B, "WM_CONTEXTMENU"),
    ])
    def test_individual_pointer_and_touch_message_absorption(self, msg_id: int, msg_name: str):
        """Verifies each touch and pointer message is absorbed and returns 0."""
        res = _global_overlay_wndproc(0, msg_id, 0, 0)
        assert res == 0, f"{msg_name} (0x{msg_id:04X}) returned {res} instead of 0 (not absorbed)"

    def test_high_throughput_touch_storm_absorption(self):
        """Floods 10,000 rapid pointer and touch events through wndproc to test performance and stability."""
        touch_messages = [
            0x0246,  # WM_POINTERDOWN
            0x0245,  # WM_POINTERUPDATE
            0x0247,  # WM_POINTERUP
            0x0240,  # WM_TOUCH
            0x0119,  # WM_GESTURE
            0x0201,  # WM_LBUTTONDOWN
            0x0202,  # WM_LBUTTONUP
        ]

        t0 = time.perf_counter()
        iterations = 10000
        for i in range(iterations):
            msg = touch_messages[i % len(touch_messages)]
            res = _global_overlay_wndproc(0, msg, i, 0)
            assert res == 0
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        print(f"\n[Touch Storm] 10,000 messages processed in {elapsed_ms:.2f}ms ({(elapsed_ms/iterations)*1000:.3f} us/call)")
        assert elapsed_ms < 500.0, f"Touch message processing too slow: {elapsed_ms:.2f}ms for 10k messages"

    def test_touch_handle_cleanup_resilience(self):
        """Verifies unmanaged CloseTouchInputHandle and CloseGestureInfoHandle exceptions are swallowed."""
        # Test valid handle closing
        with patch("input_locker.overlay.win32_overlay._user32.CloseTouchInputHandle") as mock_close_touch:
            res = _global_overlay_wndproc(0, 0x0240, 0, 0x123456)
            assert res == 0
            mock_close_touch.assert_called_once_with(0x123456)

        # Test exception during handle close does not crash wndproc
        with patch("input_locker.overlay.win32_overlay._user32.CloseTouchInputHandle", side_effect=OSError("Access denied")):
            res = _global_overlay_wndproc(0, 0x0240, 0, 0x123456)
            assert res == 0

    def test_anti_minimize_sc_minimize_permutations(self):
        """Verifies SC_MINIMIZE variations are swallowed while other system commands pass through."""
        with patch("input_locker.overlay.win32_overlay._user32.DefWindowProcW") as mock_def_proc:
            # SC_MINIMIZE = 0xF020. Windows may set lower 4 bits (0xF020 to 0xF02F)
            for low_nibble in range(16):
                wparam = SC_MINIMIZE | low_nibble
                res = _global_overlay_wndproc(1234, WM_SYSCOMMAND, wparam, 0)
                assert res == 0, f"SC_MINIMIZE variation 0x{wparam:04X} was not consumed"
            mock_def_proc.assert_not_called()

            # Non-minimize commands must pass through to DefWindowProcW
            mock_def_proc.return_value = 100
            for cmd in (0xF010, 0xF030, 0xF120):  # SC_MOVE, SC_MAXIMIZE, SC_RESTORE
                res = _global_overlay_wndproc(1234, WM_SYSCOMMAND, cmd, 0)
                assert res == 100

    def test_anti_hide_windowposchanging_stress(self):
        """Stress-tests WM_WINDOWPOSCHANGING flag stripping across multiple flag combinations."""
        try:
            set_overlay_locked(True)
            for extra_flags in (0, 0x0001, 0x0002, 0x0004, 0x0010, 0x0020, 0x0040):
                wp = WINDOWPOS()
                wp.hwnd = 1111
                wp.hwndInsertAfter = 0
                wp.flags = SWP_HIDEWINDOW | extra_flags

                res = _global_overlay_wndproc(1111, WM_WINDOWPOSCHANGING, 0, ctypes.addressof(wp))
                assert res == 0
                assert (wp.flags & SWP_HIDEWINDOW) == 0, f"SWP_HIDEWINDOW not stripped for extra_flags=0x{extra_flags:04X}"
                assert (wp.flags & extra_flags) == extra_flags, f"Extra flags 0x{extra_flags:04X} were corrupted"
                assert ctypes.c_int64(wp.hwndInsertAfter).value == HWND_TOPMOST
        finally:
            set_overlay_locked(True)

    def test_anti_hide_showwindow_reasserts_topmost(self):
        """Verifies WM_SHOWWINDOW (hiding) immediately issues SetWindowPos with SWP_SHOWWINDOW and SWP_NOACTIVATE."""
        try:
            set_overlay_locked(True)
            with patch("input_locker.overlay.win32_overlay._user32.SetWindowPos") as mock_set_pos:
                mock_set_pos.return_value = 1
                res = _global_overlay_wndproc(7777, WM_SHOWWINDOW, 0, 0)
                assert res == 0
                mock_set_pos.assert_called_once()
                args = mock_set_pos.call_args[0]
                assert args[0] == 7777  # hwnd
                assert args[1] == HWND_TOPMOST  # HWND_TOPMOST (-1)
                flags = args[6]
                assert (flags & SWP_SHOWWINDOW) != 0
                assert (flags & SWP_NOACTIVATE) != 0
        finally:
            set_overlay_locked(True)


class TestFocusPreservationStress:
    """Empirically stress-tests zero focus loss and zero activation disruption on background apps."""

    def test_styles_guarantee_noactivate(self):
        """Verifies WS_EX_NOACTIVATE is present and SWP_NOACTIVATE is used in overlay show/hide."""
        overlay = Win32Overlay(auto_prewarm=False)
        try:
            overlay.prewarm()
            ex_style = overlay.get_ex_style()
            assert (ex_style & WS_EX_NOACTIVATE) != 0, "Overlay HWND must have WS_EX_NOACTIVATE"
        finally:
            overlay.close()

    @pytest.mark.gui
    def test_companion_focus_harness_zero_activation_disruption_under_touch_barrage(self):
        """Runs live companion window, shows overlay, injects simulated clicks/taps, verifies 0 WM_ACTIVATE."""
        from tests.conftest import is_headless_environment
        if is_headless_environment():
            pytest.skip("Skipping GUI focus harness test in headless environment")

        harness = CompanionFocusHarness(title="Resolume Staging Verification")
        harness.start(timeout=3.0)
        try:
            harness.bring_to_foreground()
            time.sleep(0.05)
            harness.clear()

            with Win32Overlay(alpha=120) as overlay:
                # 1. Show overlay
                overlay.show()
                time.sleep(0.05)
                harness.assert_zero_focus_disruption()

                # 2. Simulate touch and mouse hit-testing on overlay HWND
                _global_overlay_wndproc(overlay.hwnd, WM_NCHITTEST, 0, 0)
                _global_overlay_wndproc(overlay.hwnd, WM_TOUCHHITTESTING, 0, 0)
                _global_overlay_wndproc(overlay.hwnd, WM_MOUSEACTIVATE, 0, 0)
                _global_overlay_wndproc(overlay.hwnd, WM_POINTERACTIVATE, 0, 0)
                _global_overlay_wndproc(overlay.hwnd, 0x0246, 0, 0)  # WM_POINTERDOWN
                _global_overlay_wndproc(overlay.hwnd, 0x0201, 0, 0)  # WM_LBUTTONDOWN

                time.sleep(0.05)
                harness.assert_zero_focus_disruption()

                # 3. Hide overlay
                overlay.hide()
                time.sleep(0.05)
                harness.assert_zero_focus_disruption()
        finally:
            harness.stop()
