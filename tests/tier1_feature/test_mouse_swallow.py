"""Tier 1 Feature Coverage: Global Mouse Interception (ORIGINAL_REQUEST R1).

Verifies that all mouse input (left click, right click, middle click, vertical wheel,
horizontal wheel, and movement) is suppressed completely during locked state,
and passes through normally when unlocked.
"""

import time
import pytest
from tests.harness.input_injector import InputInjector
from tests.harness.focus_harness import CompanionFocusHarness
from input_locker.hooks.hook_manager import HookManager


class TestMouseSwallowFeature:
    """Requirement R1: Intercept and swallow 100% of global mouse events during lock."""

    def test_mouse_swallow_left_click(self, focus_harness: CompanionFocusHarness):
        """Verify left mouse clicks are swallowed in locked state."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            # Send left click
            InputInjector.mouse_click(button="left")
            time.sleep(0.05)

            focus_harness.assert_zero_input_received(category="mouse")
        finally:
            hook_mgr.stop()

    def test_mouse_swallow_right_click(self, focus_harness: CompanionFocusHarness):
        """Verify right mouse clicks are swallowed in locked state."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            InputInjector.mouse_click(button="right")
            time.sleep(0.05)

            focus_harness.assert_zero_input_received(category="mouse")
        finally:
            hook_mgr.stop()

    def test_mouse_swallow_middle_click(self, focus_harness: CompanionFocusHarness):
        """Verify middle mouse clicks are swallowed in locked state."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            InputInjector.mouse_click(button="middle")
            time.sleep(0.05)

            focus_harness.assert_zero_input_received(category="mouse")
        finally:
            hook_mgr.stop()

    def test_mouse_swallow_vertical_wheel(self, focus_harness: CompanionFocusHarness):
        """Verify vertical scroll wheel events are swallowed in locked state."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            InputInjector.mouse_wheel(delta=120)
            time.sleep(0.05)

            focus_harness.assert_zero_input_received(category="mouse")
        finally:
            hook_mgr.stop()

    def test_mouse_swallow_horizontal_wheel(self, focus_harness: CompanionFocusHarness):
        """Verify horizontal scroll wheel events are swallowed in locked state."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            InputInjector.mouse_wheel(delta=120, horizontal=True)
            time.sleep(0.05)

            focus_harness.assert_zero_input_received(category="mouse")
        finally:
            hook_mgr.stop()

    def test_mouse_swallow_movement(self, focus_harness: CompanionFocusHarness):
        """Verify relative mouse move messages are swallowed in locked state."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            InputInjector.mouse_move_relative(dx=10, dy=10)
            time.sleep(0.05)

            focus_harness.assert_zero_input_received(category="mouse")
        finally:
            hook_mgr.stop()

    def test_mouse_passthrough_unlocked_baseline(self, focus_harness: CompanionFocusHarness):
        """Baseline verification: mouse clicks reach foreground window when unlocked."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=False)
        hook_mgr.start()
        try:
            # Click inside the target window (150, 150)
            InputInjector.mouse_click(button="left", x=150, y=150)
            time.sleep(0.05)

            focus_harness.assert_input_received(min_count=1, category="mouse")
        finally:
            hook_mgr.stop()
