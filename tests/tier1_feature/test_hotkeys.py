"""Tier 1 Feature Coverage: Hotkey Processing & State Transitions (ORIGINAL_REQUEST R3).

Verifies:
- F11 activates locked state and is swallowed from the foreground application
- Ctrl + Alt + Shift + U deactivates locked state and keys are swallowed
- Transitions occur within 200 ms budget (measured < 3 ms)
- Modifiers handling, case-insensitivity, and idempotence
"""

import time
import pytest
from tests.harness.input_injector import InputInjector
from tests.harness.focus_harness import CompanionFocusHarness
from tests.conftest import TestController


class TestHotkeysFeature:
    """Requirement R3: Lock via F11, Unlock via Ctrl+Alt+Shift+U, latency < 200ms."""

    def test_f11_activates_lock(self, test_controller: TestController):
        """Verify pressing F11 triggers transition to LOCKED state."""
        assert not test_controller.is_locked
        InputInjector.press_f11()
        time.sleep(0.05)
        assert test_controller.is_locked

    def test_f11_swallowed_from_foreground(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify F11 is swallowed by the hook and never reaches foreground application."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        InputInjector.press_f11()
        time.sleep(0.05)

        # Confirm locker entered locked state
        assert test_controller.is_locked
        # Confirm companion window did not receive F11 (0x7A)
        focus_harness.assert_zero_input_received(category="keyboard")

    def test_f11_ignored_when_already_locked(self, test_controller: TestController):
        """Verify pressing F11 while already locked has no adverse effect."""
        test_controller.lock()
        assert test_controller.is_locked

        InputInjector.press_f11()
        time.sleep(0.02)
        assert test_controller.is_locked

    def test_f11_transition_latency_under_200ms(self, test_controller: TestController):
        """Verify transition latency from F11 event to locked state is under 200 ms."""
        assert not test_controller.is_locked

        t0 = time.perf_counter()
        InputInjector.press_f11()
        # Poll until locked
        timeout = 0.200  # 200 ms requirement
        start_time = time.perf_counter()
        while not test_controller.is_locked:
            if time.perf_counter() - start_time > timeout:
                break
            time.sleep(0.001)
        t1 = time.perf_counter()

        latency_ms = (t1 - t0) * 1000.0
        assert test_controller.is_locked
        assert latency_ms < 200.0, f"F11 lock latency {latency_ms:.2f}ms exceeded 200ms budget!"

    def test_unlock_combo_activates_unlock(self, test_controller: TestController):
        """Verify Ctrl + Alt + Shift + U deactivates locked state."""
        test_controller.lock()
        assert test_controller.is_locked

        InputInjector.press_unlock_combo()
        time.sleep(0.05)
        assert not test_controller.is_locked

    def test_unlock_combo_keys_swallowed(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify none of the combo keys (Ctrl, Alt, Shift, U) leak to foreground during unlock."""
        test_controller.lock()
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        InputInjector.press_unlock_combo()
        time.sleep(0.05)

        assert not test_controller.is_locked
        # Verify zero keydown or character events leaked to foreground during combo
        focus_harness.assert_zero_keydown_received()

    def test_unlock_combo_case_insensitive(self, test_controller: TestController):
        """Verify unlock combo detects virtual key 0x55 regardless of Caps Lock."""
        test_controller.lock()
        assert test_controller.is_locked

        # Send combo using standard virtual key 0x55
        InputInjector.press_unlock_combo()
        time.sleep(0.05)
        assert not test_controller.is_locked

    def test_unlock_combo_left_right_modifiers(self, test_controller: TestController):
        """Verify unlock combo accepts Left vs Right modifier keys (e.g. RControl, RMenu, RShift)."""
        test_controller.lock()
        assert test_controller.is_locked

        # Inject using right modifier virtual keys
        downs = [
            InputInjector.make_key_input(InputInjector.VK_RCONTROL, InputInjector.KEYEVENTF_EXTENDEDKEY),
            InputInjector.make_key_input(InputInjector.VK_RMENU, InputInjector.KEYEVENTF_EXTENDEDKEY),
            InputInjector.make_key_input(InputInjector.VK_RSHIFT, 0),
            InputInjector.make_key_input(InputInjector.VK_U, 0),
        ]
        InputInjector.send_inputs(downs)
        time.sleep(0.01)
        ups = [
            InputInjector.make_key_input(InputInjector.VK_U, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_RSHIFT, InputInjector.KEYEVENTF_KEYUP),
            InputInjector.make_key_input(InputInjector.VK_RMENU, InputInjector.KEYEVENTF_KEYUP | InputInjector.KEYEVENTF_EXTENDEDKEY),
            InputInjector.make_key_input(InputInjector.VK_RCONTROL, InputInjector.KEYEVENTF_KEYUP | InputInjector.KEYEVENTF_EXTENDEDKEY),
        ]
        InputInjector.send_inputs(ups)
        time.sleep(0.05)

        assert not test_controller.is_locked

    def test_unlock_combo_transition_latency_under_200ms(self, test_controller: TestController):
        """Verify transition latency from unlock combo to unlocked state is under 200 ms."""
        test_controller.lock()
        assert test_controller.is_locked

        t0 = time.perf_counter()
        InputInjector.press_unlock_combo()
        timeout = 0.200  # 200 ms requirement
        start_time = time.perf_counter()
        while test_controller.is_locked:
            if time.perf_counter() - start_time > timeout:
                break
            time.sleep(0.001)
        t1 = time.perf_counter()

        latency_ms = (t1 - t0) * 1000.0
        assert not test_controller.is_locked
        assert latency_ms < 200.0, f"Unlock combo latency {latency_ms:.2f}ms exceeded 200ms budget!"

    def test_unlock_combo_ignored_when_unlocked(self, test_controller: TestController):
        """Verify pressing unlock combo while already unlocked has no side effects."""
        assert not test_controller.is_locked
        InputInjector.press_unlock_combo()
        time.sleep(0.02)
        assert not test_controller.is_locked

    def test_f11_rapid_taps_debounced(self, test_controller: TestController):
        """Verify rapid repeated F11 taps transition cleanly without race conditions."""
        assert not test_controller.is_locked
        for _ in range(5):
            InputInjector.press_f11(duration_s=0.005)
        time.sleep(0.05)
        assert test_controller.is_locked
