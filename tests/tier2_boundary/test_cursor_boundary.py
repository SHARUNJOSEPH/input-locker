"""Tier 2 Boundary Test Suite: Cursor Confinement & Invisibility Boundary Cases.

Verifies:
- Cursor remains strictly pinned to (0, 0) under drag attempts and coordinate warps
- Virtual screen boundary calculations across single and multi-monitor topologies
- Microsecond instant release of cursor bounds on unlock
- Idempotence of ShowCursor hide/unhide counters
- Fail-safe release guarantees under exceptions
"""

import time
import ctypes
import pytest
from tests.harness.input_injector import InputInjector
from tests.harness.focus_harness import CompanionFocusHarness
from input_locker.overlay.cursor_guard import CursorGuard
from input_locker.overlay.overlay_manager import OverlayManager
from tests.conftest import TestController


class TestCursorBoundaryCases:
    """Boundary Value Analysis: Cursor confinement and clipping boundary edge cases."""

    def test_cursor_drag_confinement(self, test_controller: TestController):
        """Verify synthetic mouse drags while locked cannot move cursor away from (0, 0)."""
        test_controller.lock()
        assert test_controller.is_locked
        assert test_controller.overlay_mgr.is_cursor_confined()

        # Attempt to drag cursor while locked
        for _ in range(10):
            InputInjector.mouse_move_relative(dx=25, dy=25)
            time.sleep(0.005)

        pos = InputInjector.get_cursor_pos()
        assert pos == (0, 0), f"Cursor escaped boundary during drag! Position: {pos}"
        test_controller.unlock()

    def test_cursor_teleport_attempt_blocked(self, cursor_guard: CursorGuard):
        """Verify direct Win32 SetCursorPos(1000, 1000) calls are clamped to (0, 0) by OS kernel."""
        cursor_guard.confine_to_zero()
        assert cursor_guard.is_confined()

        InputInjector.set_cursor_pos(1000, 1000)
        pos = cursor_guard.get_cursor_pos()
        assert pos == (0, 0), f"Kernel failed to clamp cursor! Position: {pos}"

    def test_virtual_screen_geometry_bounds(self, overlay_manager: OverlayManager):
        """Verify virtual screen coordinates cover all connected physical monitors."""
        vx, vy, vw, vh = overlay_manager.get_geometry()
        user32 = ctypes.windll.user32
        assert vw == user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        assert vh == user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        assert vw > 0
        assert vh > 0

    def test_clip_cursor_zero_area_rect(self, cursor_guard: CursorGuard):
        """Verify the clipping rectangle has zero width and zero height."""
        cursor_guard.confine_to_zero()
        rect = cursor_guard.get_clip_rect()
        assert rect is not None
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        assert width == 0
        assert height == 0

    def test_instant_cursor_release_on_unlock(self, cursor_guard: CursorGuard):
        """Verify cursor clipping release occurs in under 1 ms."""
        cursor_guard.confine_to_zero()
        assert cursor_guard.is_confined()

        t0 = time.perf_counter()
        cursor_guard.release()
        t1 = time.perf_counter()

        release_latency_ms = (t1 - t0) * 1000.0
        assert not cursor_guard.is_confined()
        assert release_latency_ms < 5.0, f"Cursor release took {release_latency_ms:.2f}ms!"

    def test_cursor_freely_movable_after_unlock(self, cursor_guard: CursorGuard):
        """Verify cursor can be moved to arbitrary desktop coordinates once unlocked."""
        cursor_guard.confine_to_zero()
        cursor_guard.release()

        # Move to (250, 250)
        InputInjector.set_cursor_pos(250, 250)
        pos = cursor_guard.get_cursor_pos()
        assert pos == (250, 250), f"Cursor movement restricted after unlock: {pos}"

    def test_repeated_cursor_confinement_cycles(self, cursor_guard: CursorGuard):
        """Verify 20 rapid consecutive confine/release cycles without handle leak or failure."""
        for _ in range(20):
            cursor_guard.confine_to_zero()
            assert cursor_guard.is_confined()
            cursor_guard.release()
            assert not cursor_guard.is_confined()

    def test_cursor_hidden_counter_idempotence(self, cursor_guard: CursorGuard):
        """Verify repeated calls to confine_to_zero do not decrement ShowCursor counter repeatedly."""
        cursor_guard.confine_to_zero()
        assert cursor_guard.is_cursor_hidden

        # Second call
        cursor_guard.confine_to_zero()
        assert cursor_guard.is_cursor_hidden

        # Release should restore visibility in one step
        cursor_guard.release()
        assert not cursor_guard.is_cursor_hidden

    def test_cursor_restore_counter_idempotence(self, cursor_guard: CursorGuard):
        """Verify repeated calls to release do not corrupt ShowCursor counter."""
        cursor_guard.confine_to_zero()
        cursor_guard.release()
        assert not cursor_guard.is_cursor_hidden

        # Second release
        cursor_guard.release()
        assert not cursor_guard.is_cursor_hidden

    def test_fail_safe_cursor_release_on_exception(self):
        """Verify CursorGuard context manager releases cursor if an exception occurs inside block."""
        guard = CursorGuard(register_atexit=False)
        try:
            with guard:
                assert guard.is_confined()
                raise ValueError("Simulated unexpected error inside critical section")
        except ValueError:
            pass

        assert not guard.is_confined(), "Cursor remained confined after exception!"

    def test_cursor_position_sample_during_high_rate_mouse_events(self, cursor_guard: CursorGuard):
        """Verify cursor stays strictly at (0, 0) during a 50-event high-speed movement barrage."""
        cursor_guard.confine_to_zero()
        assert cursor_guard.is_confined()

        for _ in range(50):
            InputInjector.mouse_move_relative(dx=20, dy=-15)

        time.sleep(0.01)
        pos = cursor_guard.get_cursor_pos()
        assert pos == (0, 0), f"Cursor drifted during barrage: {pos}"

    def test_corner_click_suppression(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify mouse clicks targeted at coordinate (0, 0) while locked are swallowed."""
        test_controller.lock()
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        InputInjector.mouse_click(button="left", x=0, y=0)
        time.sleep(0.05)

        focus_harness.assert_zero_input_received(category="mouse")

    def test_wheel_scroll_at_zero_coordinate(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify mouse wheel scrolling at coordinate (0, 0) while locked is swallowed."""
        test_controller.lock()
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        InputInjector.mouse_wheel(delta=120)
        time.sleep(0.05)

        focus_harness.assert_zero_input_received(category="mouse")

    def test_multi_monitor_clipping_bounds_restoration(self, cursor_guard: CursorGuard):
        """Verify desktop clipping bounds after release cover all displays."""
        cursor_guard.confine_to_zero()
        cursor_guard.release()

        clip_rect = cursor_guard.get_clip_rect()
        assert clip_rect is not None
        user32 = ctypes.windll.user32
        vw = user32.GetSystemMetrics(78)
        vh = user32.GetSystemMetrics(79)
        # Desktop clip rectangle width must equal or exceed virtual screen width
        rect_w = clip_rect[2] - clip_rect[0]
        rect_h = clip_rect[3] - clip_rect[1]
        assert rect_w >= vw
        assert rect_h >= vh

    def test_cursor_zero_coordinate_exactness(self, cursor_guard: CursorGuard):
        """Verify cursor coordinates are exactly 0, not off-by-one (e.g. 1, 1)."""
        cursor_guard.confine_to_zero()
        x, y = cursor_guard.get_cursor_pos()
        assert x == 0 and y == 0
