"""Tier 1 Feature Coverage: Overlay Display, Focus Non-Disruption & Cursor Confinement (ORIGINAL_REQUEST R2).

Verifies:
- Semi-transparent glass overlay spanning all displays (virtual desktop)
- Topmost Z-order, layered transparency, and hit-test mouse pass-through
- Zero focus disruption (0 WM_ACTIVATE / WM_KILLFOCUS) to background apps
- Cursor confinement to (0, 0) and invisibility during lock
- Clean cursor bounds and visibility restoration upon unlock
"""

import ctypes
import time
import pytest
from tests.harness.input_injector import InputInjector
from tests.harness.focus_harness import CompanionFocusHarness
from input_locker.overlay.overlay_manager import OverlayManager
from input_locker.overlay.cursor_guard import CursorGuard
from input_locker.overlay.win32_overlay import (
    WS_EX_NOACTIVATE,
    WS_EX_TRANSPARENT,
    WS_EX_LAYERED,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
)


class TestOverlayDisplayFeature:
    """Requirement R2: Full-screen semi-transparent overlay, zero focus disruption, cursor confinement."""

    def test_overlay_covers_virtual_screen(self, overlay_manager: OverlayManager):
        """Verify overlay geometry matches the complete virtual desktop covering all monitors."""
        x, y, w, h = overlay_manager.get_geometry()
        user32 = ctypes.windll.user32
        expected_w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        expected_h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

        assert w == expected_w, f"Overlay width {w} != SM_CXVIRTUALSCREEN {expected_w}"
        assert h == expected_h, f"Overlay height {h} != SM_CYVIRTUALSCREEN {expected_h}"

    def test_overlay_topmost_zorder(self, overlay_manager: OverlayManager):
        """Verify overlay window has WS_EX_TOPMOST style."""
        overlay_manager.show_overlay()
        assert overlay_manager.is_overlay_visible()
        ex_style = overlay_manager.overlay.get_ex_style()
        assert bool(ex_style & WS_EX_TOPMOST), "Overlay missing WS_EX_TOPMOST style"

    def test_overlay_layered_transparency(self, overlay_manager: OverlayManager):
        """Verify overlay window has WS_EX_LAYERED style for GPU alpha blending."""
        overlay_manager.show_overlay()
        ex_style = overlay_manager.overlay.get_ex_style()
        assert bool(ex_style & WS_EX_LAYERED), "Overlay missing WS_EX_LAYERED style"

    def test_overlay_hit_test_transparency(self, overlay_manager: OverlayManager):
        """Verify overlay window has WS_EX_TRANSPARENT style for mouse click pass-through."""
        overlay_manager.show_overlay()
        ex_style = overlay_manager.overlay.get_ex_style()
        assert bool(ex_style & WS_EX_TRANSPARENT), "Overlay missing WS_EX_TRANSPARENT style"

    def test_overlay_toolwindow_style(self, overlay_manager: OverlayManager):
        """Verify overlay window has WS_EX_TOOLWINDOW style (hidden from taskbar / Alt+Tab)."""
        overlay_manager.show_overlay()
        ex_style = overlay_manager.overlay.get_ex_style()
        assert bool(ex_style & WS_EX_TOOLWINDOW), "Overlay missing WS_EX_TOOLWINDOW style"

    def test_overlay_noactivate_style_present(self, overlay_manager: OverlayManager):
        """Verify overlay window has WS_EX_NOACTIVATE style."""
        overlay_manager.show_overlay()
        ex_style = overlay_manager.overlay.get_ex_style()
        assert bool(ex_style & WS_EX_NOACTIVATE), "Overlay missing WS_EX_NOACTIVATE style"

    def test_overlay_dynamic_alpha_adjustment(self, overlay_manager: OverlayManager):
        """Verify overlay alpha transparency can be adjusted dynamically."""
        overlay_manager.show_overlay()
        res = overlay_manager.overlay.set_alpha(180)
        assert res is True
        assert overlay_manager.overlay.alpha == 180

    def test_overlay_show_zero_focus_disruption(
        self,
        overlay_manager: OverlayManager,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify showing the overlay causes exactly 0 focus-loss messages on background window."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        # Action: Show non-activating overlay
        success = overlay_manager.show_overlay()
        assert success is True
        time.sleep(0.05)

        # Audit background focus
        focus_harness.assert_zero_focus_disruption()

    def test_overlay_hide_zero_focus_disruption(
        self,
        overlay_manager: OverlayManager,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify hiding the overlay causes exactly 0 focus-loss messages on background window."""
        overlay_manager.show_overlay()
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        # Action: Hide overlay
        success = overlay_manager.hide_overlay()
        assert success is True
        time.sleep(0.05)

        # Audit background focus
        focus_harness.assert_zero_focus_disruption()

    def test_cursor_confined_to_zero(self, cursor_guard: CursorGuard):
        """Verify CursorGuard confines clipping boundary to (0, 0, 0, 0)."""
        success = cursor_guard.confine_to_zero()
        assert success is True
        assert cursor_guard.is_confined()

        clip_rect = cursor_guard.get_clip_rect()
        assert clip_rect == (0, 0, 0, 0), f"Expected (0,0,0,0), got {clip_rect}"

    def test_cursor_pos_pinned_to_zero(self, cursor_guard: CursorGuard):
        """Verify GetCursorPos returns (0, 0) while cursor is confined."""
        cursor_guard.confine_to_zero()
        pos = cursor_guard.get_cursor_pos()
        assert pos == (0, 0), f"Expected cursor at (0, 0), got {pos}"

    def test_cursor_hidden_during_lock(self, cursor_guard: CursorGuard):
        """Verify cursor display counter is decremented below zero (hidden) during lock."""
        cursor_guard.confine_to_zero()
        assert cursor_guard.is_cursor_hidden

    def test_cursor_bounds_restored_on_unlock(self, cursor_guard: CursorGuard):
        """Verify ClipCursor is released to desktop coordinates upon unlock."""
        cursor_guard.confine_to_zero()
        assert cursor_guard.is_confined()

        # Release
        cursor_guard.release()
        assert not cursor_guard.is_confined()

        clip_rect = cursor_guard.get_clip_rect()
        assert clip_rect != (0, 0, 0, 0), "Cursor clipping was not released to full desktop!"

    def test_cursor_unhidden_on_unlock(self, cursor_guard: CursorGuard):
        """Verify cursor visibility is restored to display counter >= 0 on unlock."""
        cursor_guard.confine_to_zero()
        assert cursor_guard.is_cursor_hidden

        cursor_guard.release()
        assert not cursor_guard.is_cursor_hidden
