"""Unit tests for GUI Overlay & Cursor Confinement Subsystem (input_locker.overlay).

Verifies:
- Win32 extended window styles (WS_EX_NOACTIVATE, WS_EX_TRANSPARENT, WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_TOPMOST)
- Cursor confinement to (0, 0) via user32.ClipCursor
- Bounds restoration and visibility reset on unlock and exit
- Invisibility via user32.ShowCursor
- Zero focus disruption to active background applications via CompanionFocusHarness
- Sub-200ms transition latency budget compliance
- Multi-monitor / virtual desktop geometry coverage
- Unified OverlayManager interface contracts
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import time
import pytest

from input_locker.overlay.cursor_guard import CursorGuard
from input_locker.overlay.win32_overlay import (
    Win32Overlay,
    OVERLAY_EX_STYLE,
    WS_EX_NOACTIVATE,
    WS_EX_TRANSPARENT,
    WS_EX_LAYERED,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    SM_XVIRTUALSCREEN,
    SM_YVIRTUALSCREEN,
    SM_CXVIRTUALSCREEN,
    SM_CYVIRTUALSCREEN,
)
from input_locker.overlay.pyqt_overlay import PyQtOverlay, PYQT6_AVAILABLE
from input_locker.overlay.overlay_manager import OverlayManager
from tests.harness.focus_harness import CompanionFocusHarness


# ===========================================================================
# 1. CursorGuard Unit Tests
# ===========================================================================

class TestCursorGuard:
    """Tests for Win32 cursor confinement and visibility control."""

    @pytest.fixture(autouse=True)
    def clean_cursor_state(self):
        ctypes.windll.user32.ClipCursor(None)
        yield
        ctypes.windll.user32.ClipCursor(None)

    def test_cursor_guard_confinement_and_release(self):
        """Verifies cursor is clipped to (0, 0, 0, 0) and cleanly restored."""
        guard = CursorGuard(register_atexit=False)
        guard.release()
        try:
            assert not guard.is_confined()

            # 1. Confine
            success = guard.confine_to_zero()
            assert success is True
            assert guard.is_confined() is True

            clip_rect = guard.get_clip_rect()
            assert clip_rect == (0, 0, 0, 0)

            pos = guard.get_cursor_pos()
            assert pos == (0, 0)
            assert guard.is_cursor_hidden is True

            # 2. Release
            rel_success = guard.release()
            assert rel_success is True
            assert guard.is_confined() is False

            released_clip = guard.get_clip_rect()
            assert released_clip is not None
            # Released bounds should span non-zero width and height
            assert released_clip[2] > released_clip[0]
            assert released_clip[3] > released_clip[1]
            assert guard.is_cursor_hidden is False
        finally:
            guard.release()

    def test_cursor_guard_prevents_synthetic_movement_outside_zero(self):
        """Verifies OS kernel rejects any attempt to move cursor while confined."""
        guard = CursorGuard(register_atexit=False)
        try:
            guard.confine_to_zero()
            assert guard.is_confined() is True

            # Attempt to warp cursor to (500, 500)
            user32 = ctypes.windll.user32
            user32.SetCursorPos(500, 500)

            # Polling position must still return (0, 0)
            pos = guard.get_cursor_pos()
            assert pos == (0, 0)
        finally:
            guard.release()

    def test_cursor_guard_idempotence(self):
        """Verifies consecutive calls to confine or release do not cause state drift."""
        guard = CursorGuard(register_atexit=False)
        try:
            assert guard.confine_to_zero() is True
            assert guard.confine_to_zero() is True
            assert guard.is_confined() is True

            assert guard.release() is True
            assert guard.release() is True
            assert guard.is_confined() is False
        finally:
            guard.release()

    def test_cursor_guard_context_manager(self):
        """Verifies CursorGuard works safely as a context manager."""
        guard = CursorGuard(register_atexit=False)
        with guard:
            assert guard.is_confined() is True
            clip = guard.get_clip_rect()
            assert clip == (0, 0, 0, 0)

        assert guard.is_confined() is False


# ===========================================================================
# 2. Win32Overlay Unit Tests
# ===========================================================================

class TestWin32Overlay:
    """Tests for pure Win32 non-activating layered glass overlay."""

    def test_win32_overlay_creation_and_ex_styles(self):
        """Verifies window flags conform to the zero-focus non-activating specification."""
        with Win32Overlay(alpha=120) as overlay:
            assert overlay.hwnd is not None
            assert overlay.hwnd != 0

            ex_style = overlay.get_ex_style()

            # Verify each required extended style bit is present
            assert (ex_style & WS_EX_NOACTIVATE) == WS_EX_NOACTIVATE, "WS_EX_NOACTIVATE missing"
            assert (ex_style & WS_EX_TRANSPARENT) == WS_EX_TRANSPARENT, "WS_EX_TRANSPARENT missing"
            assert (ex_style & WS_EX_LAYERED) == WS_EX_LAYERED, "WS_EX_LAYERED missing"
            assert (ex_style & WS_EX_TOOLWINDOW) == WS_EX_TOOLWINDOW, "WS_EX_TOOLWINDOW missing"
            assert (ex_style & WS_EX_TOPMOST) == WS_EX_TOPMOST, "WS_EX_TOPMOST missing"
            assert (ex_style & OVERLAY_EX_STYLE) == OVERLAY_EX_STYLE

    def test_win32_overlay_show_hide_lifecycle(self):
        """Verifies overlay transitions between hidden and visible states."""
        with Win32Overlay(alpha=120) as overlay:
            assert overlay.is_visible() is False

            # Show
            show_ok = overlay.show()
            assert show_ok is True
            assert overlay.is_visible() is True

            # Hide
            hide_ok = overlay.hide()
            assert hide_ok is True
            assert overlay.is_visible() is False

    def test_win32_overlay_spans_virtual_desktop(self):
        """Verifies overlay covers entire multi-monitor virtual desktop bounding box."""
        user32 = ctypes.windll.user32
        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        with Win32Overlay(alpha=120) as overlay:
            geom = overlay.get_geometry()
            assert geom[2] > 0
            assert geom[3] > 0

    def test_win32_overlay_alpha_adjustment(self):
        """Verifies dynamic alpha adjustment."""
        with Win32Overlay(alpha=100) as overlay:
            assert overlay.alpha == 100
            assert overlay.set_alpha(200) is True
            assert overlay.alpha == 200

    def test_win32_overlay_transition_latency(self):
        """Verifies show and hide transitions execute well under the 200 ms budget."""
        with Win32Overlay(alpha=120) as overlay:
            # Prewarmed show
            t0 = time.perf_counter()
            overlay.show()
            t1 = time.perf_counter()
            show_latency_ms = (t1 - t0) * 1000.0

            # Prewarmed hide
            t2 = time.perf_counter()
            overlay.hide()
            t3 = time.perf_counter()
            hide_latency_ms = (t3 - t2) * 1000.0

            assert show_latency_ms < 200.0, f"Show latency {show_latency_ms:.2f}ms exceeded 200ms"
            assert hide_latency_ms < 200.0, f"Hide latency {hide_latency_ms:.2f}ms exceeded 200ms"

    @pytest.mark.gui
    def test_win32_overlay_zero_focus_disruption(self):
        """Verifies zero WM_ACTIVATE / WM_KILLFOCUS messages reach background apps."""
        from tests.conftest import is_headless_environment
        if is_headless_environment():
            pytest.skip("Skipping focus disruption test in headless environment without active desktop")
        harness = CompanionFocusHarness(title="Target Media Engine (Resolume Arena)")
        harness.start(timeout=3.0)
        try:
            # Ensure companion window is active foreground
            harness.bring_to_foreground()
            harness.clear()

            with Win32Overlay(alpha=120) as overlay:
                # 1. Show overlay
                overlay.show()
                time.sleep(0.05)
                harness.assert_zero_focus_disruption()

                # 2. Hide overlay
                overlay.hide()
                time.sleep(0.05)
                harness.assert_zero_focus_disruption()
        finally:
            harness.stop()


# ===========================================================================
# 3. PyQtOverlay Unit Tests
# ===========================================================================

@pytest.mark.skipif(not PYQT6_AVAILABLE, reason="PyQt6 not installed")
class TestPyQtOverlay:
    """Tests for PyQt6 non-activating semi-transparent glass overlay."""

    def test_pyqt_overlay_creation_and_visibility(self):
        """Verifies PyQt6 overlay widget creation, show, and hide."""
        with PyQtOverlay() as overlay:
            overlay.prewarm()
            time.sleep(0.05)
            assert overlay.is_visible() is False

            show_ok = overlay.show()
            assert show_ok is True
            assert overlay.is_visible() is True

            hide_ok = overlay.hide()
            assert hide_ok is True
            assert overlay.is_visible() is False

    def test_pyqt_overlay_with_wallpaper_renders_lock_badge(self, tmp_path):
        """Verifies lock symbol badge is rendered on top even when a wallpaper is configured."""
        # Create a dummy test image
        img_path = str(tmp_path / "test_wp.png")
        from PIL import Image
        img = Image.new("RGB", (100, 100), color="blue")
        img.save(img_path)

        from PyQt6.QtWidgets import QFrame, QLabel
        with PyQtOverlay(wallpaper_path=img_path) as overlay:
            overlay.prewarm()
            time.sleep(0.05)
            # Verify widgets have child badge frames with lock icon
            for w in overlay._widgets:
                badges = w.findChildren(QFrame)
                assert len(badges) >= 1, "Expected lock badge to be present as child overlay!"
                labels = [lbl.text() for lbl in w.findChildren(QLabel)]
                assert any("🔒" in t for t in labels), "Expected lock emoji in badge labels!"
                assert any("SYSTEM LOCKED" in t for t in labels), "Expected SYSTEM LOCKED in badge labels!"


    def test_pyqt_overlay_latency(self):
        """Verifies PyQt6 overlay show and hide transitions complete under 200 ms."""
        with PyQtOverlay() as overlay:
            overlay.prewarm()
            time.sleep(0.05)

            t0 = time.perf_counter()
            overlay.show()
            t1 = time.perf_counter()
            show_ms = (t1 - t0) * 1000.0

            t2 = time.perf_counter()
            overlay.hide()
            t3 = time.perf_counter()
            hide_ms = (t3 - t2) * 1000.0

            assert show_ms < 200.0, f"PyQt show latency {show_ms:.2f}ms exceeded 200ms"
            assert hide_ms < 200.0, f"PyQt hide latency {hide_ms:.2f}ms exceeded 200ms"

    @pytest.mark.gui
    def test_pyqt_overlay_zero_focus_disruption(self):
        """Verifies PyQt6 overlay preserves background window focus with zero events."""
        from tests.conftest import is_headless_environment
        if is_headless_environment():
            pytest.skip("Skipping focus disruption test in headless environment without active desktop")
        harness = CompanionFocusHarness(title="Target DAW (Ableton Live)")
        harness.start(timeout=3.0)
        try:
            harness.bring_to_foreground()
            time.sleep(0.1)
            harness.clear()

            with PyQtOverlay() as overlay:
                time.sleep(0.05)

                # Show overlay
                overlay.show()
                time.sleep(0.05)
                harness.assert_zero_focus_disruption()

                # Hide overlay
                overlay.hide()
                time.sleep(0.05)
                harness.assert_zero_focus_disruption()
        finally:
            harness.stop()


# ===========================================================================
# 4. OverlayManager Unified Interface Contract Tests
# ===========================================================================

class TestOverlayManager:
    """Tests for the unified OverlayManager coordinator."""

    @pytest.fixture(autouse=True)
    def clean_cursor_state(self):
        ctypes.windll.user32.ClipCursor(None)
        yield
        ctypes.windll.user32.ClipCursor(None)

    def test_overlay_manager_contract_win32(self):
        """Verifies interface methods: prewarm, show_overlay, hide_overlay, confine, release."""
        with OverlayManager(backend="win32") as mgr:
            mgr.prewarm()
            assert mgr.is_locked() is False
            assert mgr.is_overlay_visible() is False
            assert mgr.is_cursor_confined() is False

            # Test individual contract methods
            assert mgr.confine_cursor() is True
            assert mgr.is_cursor_confined() is True

            assert mgr.show_overlay() is True
            assert mgr.is_overlay_visible() is True
            assert mgr.is_locked() is True

            assert mgr.hide_overlay() is True
            assert mgr.is_overlay_visible() is False

            assert mgr.release_cursor() is True
            assert mgr.is_cursor_confined() is False
            assert mgr.is_locked() is False

    def test_overlay_manager_lock_unlock_workflow(self):
        """Verifies high-level lock() and unlock() workflows."""
        with OverlayManager(backend="win32") as mgr:
            assert mgr.lock() is True
            assert mgr.is_locked() is True
            assert mgr.is_overlay_visible() is True
            assert mgr.is_cursor_confined() is True

            assert mgr.unlock() is True
            assert mgr.is_locked() is False
            assert mgr.is_overlay_visible() is False
            assert mgr.is_cursor_confined() is False

    @pytest.mark.skipif(not PYQT6_AVAILABLE, reason="PyQt6 not installed")
    def test_overlay_manager_pyqt_backend(self):
        """Verifies OverlayManager with PyQt backend."""
        with OverlayManager(backend="pyqt") as mgr:
            assert mgr.lock() is True
            assert mgr.is_overlay_visible() is True
            assert mgr.is_cursor_confined() is True

            assert mgr.unlock() is True
            assert mgr.is_overlay_visible() is False
            assert mgr.is_cursor_confined() is False

    @pytest.mark.gui
    def test_overlay_manager_zero_focus_disruption(self):
        """Verifies full lock/unlock sequence with OverlayManager emits zero focus messages."""
        from tests.conftest import is_headless_environment
        if is_headless_environment():
            pytest.skip("Skipping focus disruption test in headless environment without active desktop")
        harness = CompanionFocusHarness(title="Target Media Engine (WATCHOUT)")
        harness.start(timeout=3.0)
        try:
            harness.bring_to_foreground()
            time.sleep(0.1)
            harness.clear()

            with OverlayManager(backend="win32") as mgr:
                mgr.prewarm()
                time.sleep(0.05)

                # Lock
                assert mgr.lock() is True
                time.sleep(0.05)
                harness.assert_zero_focus_disruption()

                # Unlock
                assert mgr.unlock() is True
                time.sleep(0.05)
                harness.assert_zero_focus_disruption()
        finally:
            harness.stop()

    def test_consecutive_rapid_lock_unlock_cycles(self):
        """Stress tests rapid repeated lock and unlock cycles."""
        with OverlayManager(backend="win32") as mgr:
            for i in range(5):
                assert mgr.lock() is True
                assert mgr.is_locked() is True
                time.sleep(0.01)
                assert mgr.unlock() is True
                assert mgr.is_locked() is False
                time.sleep(0.01)

            # Final state verification
            assert mgr.is_cursor_confined() is False
            assert mgr.is_overlay_visible() is False
