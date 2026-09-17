"""Tier 5 Adversarial: Synthetic Input Leaks & Escape Attempts.

Stress-tests:
1. Keyboard storm in locked state (100+ high-rate keystrokes: alphanumeric, punctuation, navigation, function keys).
2. Mouse drag and click storm in locked state across virtual coordinates.
3. Verification of 100% event suppression rate via HookManager and EventFilter metrics.
4. Confinement boundary check: cursor strictly pinned at (0, 0) throughout mouse storm.
5. In-depth probe of partial combo unlocking vulnerabilities (investigating GetAsyncKeyState leakage).
"""

from __future__ import annotations

import time
import pytest

from tests.conftest import TestController
from tests.harness.input_injector import InputInjector
from input_locker.hooks.hook_manager import HookManager
from input_locker.overlay.cursor_guard import CursorGuard


class TestSyntheticInputLeaksAdversarial:
    """Empirical verification of input suppression guarantees and escape boundary containment."""

    def test_high_rate_keyboard_storm_swallow_containment(self, test_controller: TestController):
        """Inject 100+ rapid keystrokes while locked and verify 100% are swallowed."""
        test_controller.lock()
        assert test_controller.is_locked

        event_filter = test_controller.hook_mgr.event_filter
        initial_swallowed = event_filter.swallowed_keyboard_count
        initial_total = event_filter.total_keyboard_count

        # Barrage of 100 keystrokes across diverse key categories
        storm_keys = (
            [ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"]
            + [0x20, 0x0D, 0x09, 0x08, 0x1B, 0x2E, 0x2D]  # Space, Enter, Tab, Backspace, Esc, Del, Insert
            + [0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x21, 0x22]  # Arrows, Home, End, PgUp, PgDn
            + [0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79]  # F1-F10
        )

        for vk in storm_keys:
            InputInjector.press_key(vk, duration_s=0.001)

        time.sleep(0.1)

        delta_total = event_filter.total_keyboard_count - initial_total
        delta_swallowed = event_filter.swallowed_keyboard_count - initial_swallowed

        print(f"\n[Keyboard Storm] Dispatched: {len(storm_keys)*2} events, Hook Seen: {delta_total}, Swallowed: {delta_swallowed}")

        assert delta_total > 0, "Hooks did not receive any keyboard events!"
        assert delta_swallowed == delta_total, (
            f"Input leak detected! Total hook events: {delta_total}, but only swallowed {delta_swallowed}"
        )

        test_controller.unlock()

    def test_mouse_drag_and_click_storm_containment(self, test_controller: TestController):
        """Inject violent mouse movements, drags, clicks, and wheel scrolls while locked."""
        test_controller.lock()
        assert test_controller.is_locked

        event_filter = test_controller.hook_mgr.event_filter
        initial_swallowed = event_filter.swallowed_mouse_count
        initial_total = event_filter.total_mouse_count

        # Rapid movement storm across screen
        for _ in range(25):
            InputInjector.mouse_move_relative(dx=100, dy=100)
            InputInjector.mouse_click(button="left")
            InputInjector.mouse_move_relative(dx=-150, dy=50)
            InputInjector.mouse_click(button="right")
            InputInjector.mouse_wheel(delta=120)
            InputInjector.mouse_move_relative(dx=50, dy=-150)
            InputInjector.mouse_click(button="middle")

        time.sleep(0.05)

        # 1. Verify cursor stayed pinned at (0, 0)
        pos = InputInjector.get_cursor_pos()
        assert pos == (0, 0), f"Cursor escaped boundary during storm! Pos: {pos}"

        # 2. Verify all mouse events that reached hook were suppressed
        delta_total = event_filter.total_mouse_count - initial_total
        delta_swallowed = event_filter.swallowed_mouse_count - initial_swallowed

        print(f"\n[Mouse Storm] Hook Seen: {delta_total}, Swallowed: {delta_swallowed}")
        if delta_total > 0:
            assert delta_swallowed == delta_total, (
                f"Mouse leak detected! Hook events: {delta_total}, Swallowed: {delta_swallowed}"
            )

        test_controller.unlock()

    def test_partial_modifier_unlock_leakage_probe(self, test_controller: TestController):
        """Adversarially probe whether partial modifier combos can trigger unauthorized unlock.
        
        Evaluates vulnerability where GetAsyncKeyState or stale active_keys allows
        unlock without all required modifiers (Ctrl, Alt, Shift).
        """
        # Case A: Missing Shift (Ctrl + Alt + U)
        test_controller.lock()
        assert test_controller.is_locked
        InputInjector.press_partial_combo(omit_shift=True, key_vk=InputInjector.VK_U)
        time.sleep(0.05)
        unlocked_without_shift = not test_controller.is_locked

        if unlocked_without_shift:
            print("\n[VULNERABILITY CONFIRMED]: System unlocked without Shift!")
            test_controller.lock()

        # Case B: Missing Ctrl (Alt + Shift + U)
        InputInjector.press_partial_combo(omit_ctrl=True, key_vk=InputInjector.VK_U)
        time.sleep(0.05)
        unlocked_without_ctrl = not test_controller.is_locked

        if unlocked_without_ctrl:
            print("\n[VULNERABILITY CONFIRMED]: System unlocked without Ctrl!")
            test_controller.lock()

        # Case C: Missing Alt (Ctrl + Shift + U)
        InputInjector.press_partial_combo(omit_alt=True, key_vk=InputInjector.VK_U)
        time.sleep(0.05)
        unlocked_without_alt = not test_controller.is_locked

        if unlocked_without_alt:
            print("\n[VULNERABILITY CONFIRMED]: System unlocked without Alt!")

        test_controller.unlock()

        # Adversarial assertion: none of these partial combinations should ever unlock
        assert not unlocked_without_shift, "SECURITY FLAW: Locker unlocked without Shift modifier!"
        assert not unlocked_without_ctrl, "SECURITY FLAW: Locker unlocked without Ctrl modifier!"
        assert not unlocked_without_alt, "SECURITY FLAW: Locker unlocked without Alt modifier!"
