"""Tier 1 Feature Coverage: Global Keyboard Interception (ORIGINAL_REQUEST R1).

Verifies that all keyboard events (alphanumeric, punctuation, function, navigation,
and modifier combos) are completely swallowed at the OS hook level while locked,
and pass through normally when unlocked.
"""

import time
import pytest
from tests.harness.input_injector import InputInjector
from tests.harness.focus_harness import CompanionFocusHarness
from input_locker.hooks.hook_manager import HookManager


class TestKeyboardSwallowFeature:
    """Requirement R1: Intercept and swallow 100% of global keyboard events during lock."""

    def test_keyboard_swallow_alphanumeric(self, focus_harness: CompanionFocusHarness):
        """Verify alphanumeric keys (A-Z, 0-9) are swallowed in locked state."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            # Inject alphanumeric keys: 'A', 'B', 'Z', '1', '9'
            vks = [ord('A'), ord('B'), ord('Z'), ord('1'), ord('9')]
            InputInjector.send_keys(vks, delay_between_s=0.01)
            time.sleep(0.05)

            # Assert target window received zero keyboard events
            focus_harness.assert_zero_input_received(category="keyboard")
        finally:
            hook_mgr.stop()

    def test_keyboard_swallow_punctuation_whitespace(self, focus_harness: CompanionFocusHarness):
        """Verify whitespace and punctuation keys are swallowed in locked state."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            # Inject Space, Enter, Tab, Backspace
            keys = [
                InputInjector.VK_SPACE,
                InputInjector.VK_RETURN,
                InputInjector.VK_TAB,
                InputInjector.VK_BACK,
            ]
            InputInjector.send_keys(keys, delay_between_s=0.01)
            time.sleep(0.05)

            focus_harness.assert_zero_input_received(category="keyboard")
        finally:
            hook_mgr.stop()

    def test_keyboard_swallow_function_keys(self, focus_harness: CompanionFocusHarness):
        """Verify function keys (F1-F10, F12) are swallowed in locked state."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            f_keys = [
                InputInjector.VK_F1,
                InputInjector.VK_F2,
                InputInjector.VK_F5,
                InputInjector.VK_F10,
                InputInjector.VK_F12,
            ]
            InputInjector.send_keys(f_keys, delay_between_s=0.01)
            time.sleep(0.05)

            focus_harness.assert_zero_input_received(category="keyboard")
        finally:
            hook_mgr.stop()

    def test_keyboard_swallow_navigation_keys(self, focus_harness: CompanionFocusHarness):
        """Verify navigation keys (Arrows, Home, End, PgUp, PgDn, Delete) are swallowed."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            nav_keys = [
                InputInjector.VK_LEFT,
                InputInjector.VK_RIGHT,
                InputInjector.VK_UP,
                InputInjector.VK_DOWN,
                InputInjector.VK_HOME,
                InputInjector.VK_END,
                InputInjector.VK_PRIOR,
                InputInjector.VK_NEXT,
                InputInjector.VK_DELETE,
            ]
            InputInjector.send_keys(nav_keys, delay_between_s=0.01)
            time.sleep(0.05)

            focus_harness.assert_zero_input_received(category="keyboard")
        finally:
            hook_mgr.stop()

    def test_keyboard_passthrough_unlocked_baseline(self, focus_harness: CompanionFocusHarness):
        """Baseline verification: keys pass through to foreground window when unlocked."""
        focus_harness.bring_to_foreground()
        # Click on companion window client area to ensure true OS keyboard focus
        InputInjector.mouse_click(button="left", x=150, y=150)
        time.sleep(0.05)
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=False)
        hook_mgr.start()
        try:
            # Inject 'K' key
            InputInjector.press_key(ord('K'), duration_s=0.01)
            time.sleep(0.05)

            # Assert target window DID receive the key
            focus_harness.assert_input_received(min_count=1, category="keyboard")
        finally:
            hook_mgr.stop()

    def test_keyboard_swallow_system_shortcuts(self, focus_harness: CompanionFocusHarness):
        """Verify system keys and modifier combinations (Alt+Tab, Win keys) are swallowed."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        hook_mgr = HookManager(swallow_active=True)
        hook_mgr.start()
        try:
            # Alt + Tab simulation
            InputInjector.key_down(InputInjector.VK_MENU)
            InputInjector.press_key(InputInjector.VK_TAB, duration_s=0.01)
            InputInjector.key_up(InputInjector.VK_MENU)

            # Windows key
            InputInjector.press_key(InputInjector.VK_LWIN, duration_s=0.01)
            time.sleep(0.05)

            focus_harness.assert_zero_input_received(category="keyboard")
        finally:
            hook_mgr.stop()
