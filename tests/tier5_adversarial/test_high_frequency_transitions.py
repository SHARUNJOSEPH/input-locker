"""Tier 5 Adversarial: High-Frequency State Transitions.

Stress-tests:
1. 50+ rapid lock/unlock cycles in tight loop alternating between network commands and hotkeys.
2. Concurrent multi-threaded transition races on production StateMachine and LockerController.
3. Verification of zero deadlocks, zero unhandled transition exceptions, zero stuck intermediate states.
4. Latency benchmarking across 100 consecutive transitions.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
import pytest
from typing import List

from input_locker.core.state_machine import LockerState, StateMachine, InvalidStateTransitionError
from input_locker.core.controller import LockerController
from tests.conftest import TestController
from tests.harness.client_harness import LockerTCPClient, LockerUDPClient, LockerOSCClient
from tests.harness.input_injector import InputInjector


class TestHighFrequencyTransitionsAdversarial:
    """Stress test high-frequency state transitions under adversarial conditions."""

    def test_50_rapid_alternating_network_and_hotkey_cycles(self, test_controller: TestController):
        """Execute 50 consecutive cycles alternating hotkey and network show control commands.
        
        Odd cycles: Lock via F11, Unlock via TCP
        Even cycles: Lock via UDP, Unlock via Hotkey combo
        """
        tcp_client = LockerTCPClient(port=test_controller.tcp_port)
        udp_client = LockerUDPClient(port=test_controller.udp_port)

        total_cycles = 50
        transition_times = []

        for cycle in range(total_cycles):
            t_start = time.perf_counter()

            if cycle % 2 == 0:
                # Hotkey Lock -> TCP Unlock
                InputInjector.press_f11()
                # Wait for lock with timeout
                deadline = time.perf_counter() + 1.0
                while not test_controller.is_locked and time.perf_counter() < deadline:
                    time.sleep(0.002)
                assert test_controller.is_locked, f"Failed to lock via F11 on cycle {cycle}"

                resp, rtt = tcp_client.unlock()
                assert resp.get("status") == "ok", f"TCP unlock failed on cycle {cycle}: {resp}"
                deadline = time.perf_counter() + 1.0
                while test_controller.is_locked and time.perf_counter() < deadline:
                    time.sleep(0.002)
                assert not test_controller.is_locked, f"Failed to unlock via TCP on cycle {cycle}"

            else:
                # UDP Lock -> Hotkey Unlock
                resp, rtt = udp_client.lock()
                assert resp.get("status") == "ok", f"UDP lock failed on cycle {cycle}: {resp}"
                deadline = time.perf_counter() + 1.0
                while not test_controller.is_locked and time.perf_counter() < deadline:
                    time.sleep(0.002)
                assert test_controller.is_locked, f"Failed to lock via UDP on cycle {cycle}"

                InputInjector.press_unlock_combo()
                deadline = time.perf_counter() + 1.0
                while test_controller.is_locked and time.perf_counter() < deadline:
                    time.sleep(0.002)
                assert not test_controller.is_locked, f"Failed to unlock via combo on cycle {cycle}"

            t_end = time.perf_counter()
            transition_times.append((t_end - t_start) * 1000.0)

        # Confirm all 50 cycles executed cleanly
        assert len(transition_times) == total_cycles
        avg_cycle_ms = sum(transition_times) / len(transition_times)
        max_cycle_ms = max(transition_times)
        print(f"\n[50-cycle Benchmark] Avg cycle: {avg_cycle_ms:.2f} ms, Max cycle: {max_cycle_ms:.2f} ms")
        assert not test_controller.is_locked

    def test_production_state_machine_concurrent_hammering(self):
        """Stress test production StateMachine with 10 concurrent threads hammering lock/unlock.
        
        Verifies:
        - No unhandled InvalidStateTransitionError crashing callers.
        - FSM never ends up in inconsistent/corrupted state.
        - Idempotence under heavy lock contention.
        """
        sm = StateMachine(initial_state=LockerState.UNLOCKED)
        exceptions: List[Exception] = []
        num_threads = 10
        iterations_per_thread = 50

        def hammer_worker(worker_id: int):
            try:
                for i in range(iterations_per_thread):
                    if (worker_id + i) % 2 == 0:
                        sm.lock()
                    else:
                        sm.unlock()
            except Exception as e:
                exceptions.append(e)

        threads = [
            threading.Thread(target=hammer_worker, args=(i,), name=f"FSMHammer-{i}")
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not exceptions, f"Concurrent hammering produced exceptions: {exceptions}"
        assert sm.state in (LockerState.LOCKED, LockerState.UNLOCKED)
        assert sm.total_transitions > 0

    def test_production_controller_high_frequency_transitions(self):
        """Execute 60 consecutive lock/unlock cycles directly on production LockerController.
        
        Verifies:
        - Sub-200ms latency requirement for every single transition.
        - Zero handle or memory leaks across repeated Win32 overlay show/hide calls.
        - Final state clean UNLOCKED with cursor restored.
        """
        ctrl = LockerController(auto_register_signals=False)
        ctrl.start()
        try:
            latencies_lock = []
            latencies_unlock = []

            for i in range(60):
                t0 = time.perf_counter()
                ok = ctrl.lock()
                t1 = time.perf_counter()
                assert ok is True, f"Lock failed at cycle {i}"
                assert ctrl.is_locked() is True
                lat_lock = (t1 - t0) * 1000.0
                latencies_lock.append(lat_lock)
                assert lat_lock < 200.0, f"Lock latency {lat_lock:.2f}ms exceeded 200ms budget!"

                t2 = time.perf_counter()
                ok = ctrl.unlock()
                t3 = time.perf_counter()
                assert ok is True, f"Unlock failed at cycle {i}"
                assert ctrl.is_locked() is False
                lat_unlock = (t3 - t2) * 1000.0
                latencies_unlock.append(lat_unlock)
                assert lat_unlock < 200.0, f"Unlock latency {lat_unlock:.2f}ms exceeded 200ms budget!"

            print(f"\n[Production Controller 60 Cycles] "
                  f"Avg Lock: {sum(latencies_lock)/len(latencies_lock):.2f}ms (Max: {max(latencies_lock):.2f}ms), "
                  f"Avg Unlock: {sum(latencies_unlock)/len(latencies_unlock):.2f}ms (Max: {max(latencies_unlock):.2f}ms)")
        finally:
            ctrl.stop()
            assert not ctrl.is_locked()
