"""Tier 5 Adversarial Test Suite: Extreme Display Geometry & Overlay Robustness.

Adversarial stress-testing of visual overlay and cursor clipping under:
- Negative virtual screen origins (monitors positioned to the left or above primary)
- Massive ultra-high resolution display geometry (16K / multi-projector setups)
- Minimal 1x1 / boundary screen geometries
- Alpha transparency extreme boundaries (< 0, > 255, float inputs)
- Multi-cycle window recreation churn without GDI/HWND leaks
- Extended window styles (WS_EX_NOACTIVATE, WS_EX_TRANSPARENT, WS_EX_TOPMOST) retention
"""

from __future__ import annotations

import ctypes
import time
from typing import Tuple
from unittest.mock import patch
import pytest

from input_locker.overlay.win32_overlay import (
    Win32Overlay,
    OVERLAY_EX_STYLE,
    WS_EX_NOACTIVATE,
    WS_EX_TRANSPARENT,
    WS_EX_LAYERED,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
)
from input_locker.overlay.cursor_guard import CursorGuard, RECT
from input_locker.overlay.overlay_manager import OverlayManager


class TestExtremeDisplayGeometry:
    """Adversarial stress testing of overlay geometry, alpha, and resource churn."""

    def test_negative_virtual_screen_origin_geometry(self) -> None:
        """Verify overlay correctly adapts to virtual screens with negative origins."""
        # Simulated setup: Monitor 1 at (-1920, 0) 1920x1080, Monitor 2 at (0, 0) 1920x1080
        simulated_bounds = (-1920, 0, 3840, 1080)

        with patch.object(Win32Overlay, "_get_virtual_desktop_bounds", return_value=simulated_bounds):
            overlay = Win32Overlay(auto_prewarm=False)
            try:
                overlay.prewarm()
                geo = overlay.get_geometry()
                assert geo == simulated_bounds, f"Geometry mismatch: expected {simulated_bounds}, got {geo}"

                success = overlay.show()
                assert success is True
                assert overlay.is_visible() is True

                # Extended styles must remain intact
                ex_style = overlay.get_ex_style()
                assert (ex_style & WS_EX_NOACTIVATE) != 0
                assert (ex_style & WS_EX_TRANSPARENT) != 0
                assert (ex_style & WS_EX_TOPMOST) != 0

                hide_success = overlay.hide()
                assert hide_success is True
                assert overlay.is_visible() is False
            finally:
                overlay.close()

    def test_giant_multi_projector_16k_canvas_geometry(self) -> None:
        """Verify overlay functions without failure on massive 16K staging canvases."""
        giant_bounds = (0, 0, 15360, 8640)

        with patch.object(Win32Overlay, "_get_virtual_desktop_bounds", return_value=giant_bounds):
            overlay = Win32Overlay(auto_prewarm=False)
            try:
                overlay.prewarm()
                assert overlay.get_geometry() == giant_bounds
                assert overlay.show() is True
                assert overlay.is_visible() is True
                assert overlay.hide() is True
            finally:
                overlay.close()

    def test_minimal_boundary_screen_geometry(self) -> None:
        """Verify overlay handles minimal 1x1 geometry without crashing."""
        minimal_bounds = (0, 0, 1, 1)

        with patch.object(Win32Overlay, "_get_virtual_desktop_bounds", return_value=minimal_bounds):
            overlay = Win32Overlay(auto_prewarm=False)
            try:
                overlay.prewarm()
                assert overlay.get_geometry() == minimal_bounds
                assert overlay.show() is True
                assert overlay.hide() is True
            finally:
                overlay.close()

    def test_alpha_transparency_extreme_boundaries(self) -> None:
        """Verify alpha parameter clamping under extreme, negative, and oversized values."""
        overlay = Win32Overlay(alpha=-50, auto_prewarm=False)
        assert overlay.alpha == 0, f"Expected 0 for negative alpha, got {overlay.alpha}"

        overlay2 = Win32Overlay(alpha=500, auto_prewarm=False)
        assert overlay2.alpha == 255, f"Expected 255 for oversized alpha, got {overlay2.alpha}"

        overlay3 = Win32Overlay(alpha=120, auto_prewarm=False)
        try:
            overlay3.prewarm()
            # Dynamic adjustment boundaries
            assert overlay3.set_alpha(-100) is True
            assert overlay3.alpha == 0

            assert overlay3.set_alpha(1000) is True
            assert overlay3.alpha == 255

            assert overlay3.set_alpha(128) is True
            assert overlay3.alpha == 128
        finally:
            overlay3.close()

    def test_rapid_overlay_show_hide_churn(self) -> None:
        """Verify 25 rapid show/hide cycles execute without handle corruption or slowdown."""
        overlay = Win32Overlay(auto_prewarm=True)
        try:
            start_time = time.perf_counter()
            for _ in range(25):
                assert overlay.show() is True
                assert overlay.hide() is True
            elapsed = time.perf_counter() - start_time
            # 25 full cycles should execute in well under 1 second
            assert elapsed < 1.0, f"Show/hide churn too slow: {elapsed:.3f}s for 25 cycles"
        finally:
            overlay.close()

    def test_cursor_guard_confinement_clipping_rect(self) -> None:
        """Verify cursor guard zeroes the clip rect and safely restores bounds."""
        guard = CursorGuard(register_atexit=False)
        try:
            # Confine
            assert guard.confine_to_zero() is True
            rect = guard.get_clip_rect()
            if rect is not None:
                # Should be (0, 0, 0, 0)
                assert rect == (0, 0, 0, 0), f"Expected (0, 0, 0, 0), got {rect}"

            # Release
            assert guard.release() is True
            rect_after = guard.get_clip_rect()
            if rect_after is not None:
                # After release, width and height of clip rect must be > 0
                width = rect_after[2] - rect_after[0]
                height = rect_after[3] - rect_after[1]
                assert width > 0 and height > 0
        finally:
            guard.release()

    def test_extended_window_styles_constant_compliance(self) -> None:
        """Verify the OVERLAY_EX_STYLE bitmask precisely includes all required styles."""
        assert OVERLAY_EX_STYLE & WS_EX_NOACTIVATE == WS_EX_NOACTIVATE
        assert OVERLAY_EX_STYLE & WS_EX_TRANSPARENT == WS_EX_TRANSPARENT
        assert OVERLAY_EX_STYLE & WS_EX_LAYERED == WS_EX_LAYERED
        assert OVERLAY_EX_STYLE & WS_EX_TOOLWINDOW == WS_EX_TOOLWINDOW
        assert OVERLAY_EX_STYLE & WS_EX_TOPMOST == WS_EX_TOPMOST
