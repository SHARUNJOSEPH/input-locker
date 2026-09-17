"""Tier 3 Combination Test Suite: Concurrent Triggers & Race Condition Stress.

Verifies:
- Simultaneous execution of network lock command and physical F11 hotkey
- Simultaneous execution of network unlock command and unlock combo
- Barrage of high-frequency input events firing during state transitions
- Zero state machine deadlock, corruption, or hook unhooking
"""

import time
import threading
import pytest
from tests.harness.input_injector import InputInjector
from tests.harness.client_harness import LockerTCPClient, LockerUDPClient
from tests.harness.focus_harness import CompanionFocusHarness
from tests.conftest import TestController


class TestConcurrentTriggersCombination:
    """Pairwise verification: Race condition resistance across concurrent control channels."""

    def test_simultaneous_network_lock_and_hotkey_f11(self, test_controller: TestController):
        """Verify simultaneous network lock command and F11 hotkey resolve cleanly without race."""
        assert not test_controller.is_locked
        barrier = threading.Barrier(2)

        def worker_net():
            barrier.wait()
            cl = LockerTCPClient(port=test_controller.tcp_port)
            cl.lock()

        def worker_hotkey():
            barrier.wait()
            InputInjector.press_f11()

        t1 = threading.Thread(target=worker_net)
        t2 = threading.Thread(target=worker_hotkey)
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)
        time.sleep(0.05)

        assert test_controller.is_locked
        test_controller.unlock()

    def test_simultaneous_network_unlock_and_hotkey_combo(self, test_controller: TestController):
        """Verify simultaneous network unlock command and unlock combo resolve cleanly."""
        test_controller.lock()
        assert test_controller.is_locked
        barrier = threading.Barrier(2)

        def worker_net():
            barrier.wait()
            cl = LockerUDPClient(port=test_controller.udp_port)
            cl.unlock()

        def worker_hotkey():
            barrier.wait()
            InputInjector.press_unlock_combo()

        t1 = threading.Thread(target=worker_net)
        t2 = threading.Thread(target=worker_hotkey)
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)
        time.sleep(0.05)

        assert not test_controller.is_locked

    def test_high_rate_synthetic_input_during_state_transitions(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Verify continuous barrage of synthetic input while cycling lock states does not deadlock."""
        stop_flag = threading.Event()

        def spammer():
            while not stop_flag.is_set():
                InputInjector.mouse_move_relative(dx=5, dy=5)
                time.sleep(0.002)

        t_spam = threading.Thread(target=spammer)
        t_spam.start()

        try:
            cl = LockerTCPClient(port=test_controller.tcp_port)
            for _ in range(5):
                cl.lock()
                time.sleep(0.02)
                assert test_controller.is_locked
                cl.unlock()
                time.sleep(0.02)
                assert not test_controller.is_locked
        finally:
            stop_flag.set()
            t_spam.join(timeout=2.0)
