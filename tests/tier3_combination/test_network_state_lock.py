"""Tier 3 Combination Test Suite: Network Control & Hotkey State Cross-Locking.

Verifies:
- Locking via network while physical/synthetic keys are actively depressed
- Unlocking via hotkey combo after network lock activation
- Unlocking via network command after hotkey (F11) lock activation
- Clean modifier state reset when unlocking via network while modifiers are held
"""

import time
import pytest
from tests.harness.input_injector import InputInjector
from tests.harness.client_harness import LockerTCPClient, LockerUDPClient
from tests.harness.focus_harness import CompanionFocusHarness
from tests.conftest import TestController


class TestNetworkStateLockCombination:
    """Pairwise verification: Network control interplaying with local OS hooks and hotkeys."""

    def test_network_lock_while_keys_held(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify locking via network while keys are depressed immediately begins swallowing."""
        assert not test_controller.is_locked
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        # Depress 'A' key
        InputInjector.key_down(ord('A'))
        time.sleep(0.01)

        # Trigger network lock
        client = LockerTCPClient(port=test_controller.tcp_port)
        client.lock()
        assert test_controller.is_locked

        focus_harness.clear()

        # Now release 'A' and press 'B' while locked
        InputInjector.key_up(ord('A'))
        InputInjector.press_key(ord('B'), duration_s=0.01)
        time.sleep(0.05)

        # Confirm nothing leaked while locked
        focus_harness.assert_zero_input_received(category="keyboard")
        test_controller.unlock()

    def test_hotkey_unlock_after_network_lock(self, test_controller: TestController):
        """Verify utility locked via network command can be unlocked via local hotkey combo."""
        assert not test_controller.is_locked

        # Lock via UDP
        udp_client = LockerUDPClient(port=test_controller.udp_port)
        udp_client.lock()
        time.sleep(0.05)
        assert test_controller.is_locked

        # Unlock via hotkey combo
        InputInjector.press_unlock_combo()
        time.sleep(0.05)
        assert not test_controller.is_locked

    def test_network_unlock_after_hotkey_lock(self, test_controller: TestController):
        """Verify utility locked via local F11 hotkey can be unlocked via remote network command."""
        assert not test_controller.is_locked

        # Lock via F11
        InputInjector.press_f11()
        time.sleep(0.05)
        assert test_controller.is_locked

        # Unlock via TCP
        tcp_client = LockerTCPClient(port=test_controller.tcp_port)
        resp, _ = tcp_client.unlock()
        assert resp.get("status") == "ok"
        assert not test_controller.is_locked

    def test_modifiers_held_during_network_unlock(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify that when network unlock arrives while Shift/Alt are held, modifiers don't get stuck."""
        test_controller.lock()
        assert test_controller.is_locked
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        # Hold Shift down
        InputInjector.key_down(InputInjector.VK_SHIFT)
        time.sleep(0.01)

        # Network unlock
        client = LockerUDPClient(port=test_controller.udp_port)
        client.unlock()
        time.sleep(0.05)
        assert not test_controller.is_locked

        # Release Shift
        InputInjector.key_up(InputInjector.VK_SHIFT)
        time.sleep(0.01)

        # Press normal key 'P'
        InputInjector.press_key(ord('P'), duration_s=0.01)
        time.sleep(0.05)

        # Confirm keystroke received
        focus_harness.assert_input_received(min_count=1, category="keyboard")
