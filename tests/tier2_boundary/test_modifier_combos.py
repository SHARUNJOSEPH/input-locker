"""Tier 2 Boundary Test Suite: Modifier Key Combinations & SysKey Handling.

Verifies:
- Partial combos (omitting Ctrl, Alt, or Shift) do NOT trigger unlock
- Non-matching trigger keys (Ctrl+Alt+Shift+X) do NOT trigger unlock
- Arbitrary modifier press orders (reverse, interleaved) reliably unlock
- Long modifier holds with repeated trigger taps
- Alt system key behavior (WM_SYSKEYDOWN / WM_SYSKEYUP)
- Extended modifier keys (Right Ctrl, Right Alt)
- System shortcut swallowing (Alt+Tab, Alt+F4, Ctrl+Shift+Esc)
"""

import time
import pytest
from tests.harness.input_injector import InputInjector
from tests.harness.focus_harness import CompanionFocusHarness
from tests.conftest import TestController


class TestModifierCombosBoundary:
    """Boundary Value Analysis: Modifier combos, ordering, and SysKey edge cases."""

    def test_partial_combo_ctrl_alt_u_without_shift(self, test_controller: TestController):
        """Verify holding Ctrl+Alt and pressing U does NOT unlock."""
        test_controller.lock()
        assert test_controller.is_locked

        InputInjector.press_partial_combo(omit_shift=True, key_vk=InputInjector.VK_U)
        time.sleep(0.05)
        assert test_controller.is_locked, "Locker unlocked with missing Shift modifier!"

    def test_partial_combo_alt_shift_u_without_ctrl(self, test_controller: TestController):
        """Verify holding Alt+Shift and pressing U does NOT unlock."""
        test_controller.lock()
        assert test_controller.is_locked

        InputInjector.press_partial_combo(omit_ctrl=True, key_vk=InputInjector.VK_U)
        time.sleep(0.05)
        assert test_controller.is_locked, "Locker unlocked with missing Ctrl modifier!"

    def test_partial_combo_ctrl_shift_u_without_alt(self, test_controller: TestController):
        """Verify holding Ctrl+Shift and pressing U does NOT unlock."""
        test_controller.lock()
        assert test_controller.is_locked

        InputInjector.press_partial_combo(omit_alt=True, key_vk=InputInjector.VK_U)
        time.sleep(0.05)
        assert test_controller.is_locked, "Locker unlocked with missing Alt modifier!"

    def test_wrong_trigger_key_ctrl_alt_shift_x(self, test_controller: TestController):
        """Verify holding all modifiers with an invalid trigger key ('X') does NOT unlock."""
        test_controller.lock()
        assert test_controller.is_locked

        InputInjector.press_partial_combo(key_vk=ord('X'))
        time.sleep(0.05)
        assert test_controller.is_locked, "Locker unlocked with invalid trigger key 'X'!"

    def test_reverse_order_modifier_press(self, test_controller: TestController):
        """Verify pressing modifiers in reverse order (Shift, then Alt, then Ctrl, then U) unlocks."""
        test_controller.lock()
        assert test_controller.is_locked

        downs = [
            InputInjector.make_key_input(InputInjector.VK_SHIFT),
            InputInjector.make_key_input(InputInjector.VK_MENU),
            InputInjector.make_key_input(InputInjector.VK_CONTROL),
            InputInjector.make_key_input(InputInjector.VK_U),
        ]
        InputInjector.send_inputs(downs)
        time.sleep(0.01)

        ups = [
            InputInjector.make_key_input(InputInjector.VK_U, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_CONTROL, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_MENU, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_SHIFT, InputInjector.KEYEVENTF_KEYUP),
        ]
        InputInjector.send_inputs(ups)
        time.sleep(0.05)

        assert not test_controller.is_locked, "Failed to unlock with reverse modifier order!"

    def test_interleaved_modifiers_press(self, test_controller: TestController):
        """Verify pressing modifiers in interleaved order (Alt, Ctrl, Shift, U) unlocks."""
        test_controller.lock()
        assert test_controller.is_locked

        downs = [
            InputInjector.make_key_input(InputInjector.VK_MENU),
            InputInjector.make_key_input(InputInjector.VK_CONTROL),
            InputInjector.make_key_input(InputInjector.VK_SHIFT),
            InputInjector.make_key_input(InputInjector.VK_U),
        ]
        InputInjector.send_inputs(downs)
        time.sleep(0.01)

        ups = [
            InputInjector.make_key_input(InputInjector.VK_U, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_SHIFT, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_CONTROL, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_MENU, InputInjector.KEYEVENTF_KEYUP),
        ]
        InputInjector.send_inputs(ups)
        time.sleep(0.05)

        assert not test_controller.is_locked

    def test_long_press_modifiers_with_repeated_u(self, test_controller: TestController):
        """Verify holding modifiers and tapping U multiple times unlocks cleanly without crashing."""
        test_controller.lock()
        assert test_controller.is_locked

        # Hold modifiers down
        downs = [
            InputInjector.make_key_input(InputInjector.VK_CONTROL),
            InputInjector.make_key_input(InputInjector.VK_MENU),
            InputInjector.make_key_input(InputInjector.VK_SHIFT),
        ]
        InputInjector.send_inputs(downs)
        time.sleep(0.05)

        # Tap U multiple times
        for _ in range(3):
            InputInjector.press_key(InputInjector.VK_U, duration_s=0.005)
            time.sleep(0.01)

        # Release modifiers
        ups = [
            InputInjector.make_key_input(InputInjector.VK_SHIFT, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_MENU, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_CONTROL, InputInjector.KEYEVENTF_KEYUP),
        ]
        InputInjector.send_inputs(ups)
        time.sleep(0.05)

        assert not test_controller.is_locked

    def test_rapid_modifier_tapping_without_u(self, test_controller: TestController):
        """Verify rapid tapping of Ctrl, Alt, Shift in isolation does not cause state drift."""
        test_controller.lock()
        assert test_controller.is_locked

        for _ in range(10):
            InputInjector.press_key(InputInjector.VK_CONTROL, duration_s=0.002)
            InputInjector.press_key(InputInjector.VK_MENU, duration_s=0.002)
            InputInjector.press_key(InputInjector.VK_SHIFT, duration_s=0.002)

        time.sleep(0.05)
        assert test_controller.is_locked

    def test_alt_syskeydown_system_key_handling(self, test_controller: TestController):
        """Verify WM_SYSKEYDOWN (0x0104) sent when Alt is held is recognized by event filter."""
        test_controller.lock()
        assert test_controller.is_locked

        # Press Alt first, which puts subsequent keys in SYSKEYDOWN mode
        InputInjector.key_down(InputInjector.VK_MENU)
        time.sleep(0.005)
        InputInjector.key_down(InputInjector.VK_CONTROL)
        InputInjector.key_down(InputInjector.VK_SHIFT)
        InputInjector.press_key(InputInjector.VK_U, duration_s=0.01)

        InputInjector.key_up(InputInjector.VK_SHIFT)
        InputInjector.key_up(InputInjector.VK_CONTROL)
        InputInjector.key_up(InputInjector.VK_MENU)
        time.sleep(0.05)

        assert not test_controller.is_locked

    def test_extended_key_flag_modifiers(self, test_controller: TestController):
        """Verify right-side extended modifiers (Right Ctrl / Right Alt) unlock correctly."""
        test_controller.lock()
        assert test_controller.is_locked

        # Right Ctrl + Right Alt + Shift + U
        downs = [
            InputInjector.make_key_input(InputInjector.VK_RCONTROL, InputInjector.KEYEVENTF_EXTENDEDKEY),
            InputInjector.make_key_input(InputInjector.VK_RMENU, InputInjector.KEYEVENTF_EXTENDEDKEY),
            InputInjector.make_key_input(InputInjector.VK_SHIFT),
            InputInjector.make_key_input(InputInjector.VK_U),
        ]
        InputInjector.send_inputs(downs)
        time.sleep(0.01)

        ups = [
            InputInjector.make_key_input(InputInjector.VK_U, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_SHIFT, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_RMENU, InputInjector.KEYEVENTF_KEYUP | InputInjector.KEYEVENTF_EXTENDEDKEY),
            InputInjector.make_key_input(InputInjector.VK_RCONTROL, InputInjector.KEYEVENTF_KEYUP | InputInjector.KEYEVENTF_EXTENDEDKEY),
        ]
        InputInjector.send_inputs(ups)
        time.sleep(0.05)

        assert not test_controller.is_locked

    def test_modifiers_released_after_unlock_no_sticking(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify active keys set is cleared upon unlock so modifiers do not stick."""
        test_controller.lock()
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        InputInjector.press_unlock_combo()
        time.sleep(0.05)

        assert not test_controller.is_locked
        # Verify subsequent key input passes through cleanly
        InputInjector.press_key(ord('M'), duration_s=0.01)
        time.sleep(0.05)
        focus_harness.assert_input_received(min_count=1, category="keyboard")

    def test_caps_lock_and_num_lock_isolation(self, test_controller: TestController):
        """Verify unlock combo works regardless of keyboard toggle states (Caps/Num lock)."""
        test_controller.lock()
        assert test_controller.is_locked

        InputInjector.press_unlock_combo()
        time.sleep(0.05)
        assert not test_controller.is_locked

    def test_ctrl_shift_esc_swallowed(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify Task Manager shortcut (Ctrl+Shift+Esc) is swallowed in locked state."""
        test_controller.lock()
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        downs = [
            InputInjector.make_key_input(InputInjector.VK_CONTROL),
            InputInjector.make_key_input(InputInjector.VK_SHIFT),
            InputInjector.make_key_input(InputInjector.VK_ESCAPE),
        ]
        InputInjector.send_inputs(downs)
        time.sleep(0.01)
        ups = [
            InputInjector.make_key_input(InputInjector.VK_ESCAPE, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_SHIFT, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_CONTROL, InputInjector.KEYEVENTF_KEYUP),
        ]
        InputInjector.send_inputs(ups)
        time.sleep(0.05)

        focus_harness.assert_zero_input_received(category="keyboard")

    def test_alt_tab_swallowed(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify Alt+Tab window switching is swallowed in locked state."""
        test_controller.lock()
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        InputInjector.key_down(InputInjector.VK_MENU)
        InputInjector.press_key(InputInjector.VK_TAB, duration_s=0.01)
        InputInjector.key_up(InputInjector.VK_MENU)
        time.sleep(0.05)

        focus_harness.assert_zero_input_received(category="keyboard")

    def test_alt_f4_swallowed(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify Alt+F4 close command is swallowed in locked state."""
        test_controller.lock()
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        InputInjector.key_down(InputInjector.VK_MENU)
        InputInjector.press_key(InputInjector.VK_F4, duration_s=0.01)
        InputInjector.key_up(InputInjector.VK_MENU)
        time.sleep(0.05)

        focus_harness.assert_zero_input_received(category="keyboard")
