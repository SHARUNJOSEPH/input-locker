"""Tier 5 Adversarial: Concurrent Stress & Race Conditions.

Stress-tests:
1. Simultaneous network lock/unlock command while physical keys are being pressed.
2. Simultaneous hotkey press while bursts of network packets arrive.
3. Multi-threaded race between event filter callbacks and network server dispatchers.
4. Verify zero hook thread hangs, zero deadlocks, zero dropped listeners.
"""

from __future__ import annotations

import threading
import time
import pytest
from typing import List

from tests.conftest import TestController
from tests.harness.client_harness import LockerTCPClient, LockerUDPClient, LockerOSCClient
from tests.harness.input_injector import InputInjector


class TestConcurrentRacesAdversarial:
    """Stress test concurrent races between network commands and OS input hooks."""

    def test_simultaneous_network_lock_while_physical_keys_pressed(self, test_controller: TestController):
        """Inject continuous physical keyboard events while sending rapid network lock/unlock."""
        udp_client = LockerUDPClient(port=test_controller.udp_port)
        stop_event = threading.Event()
        errors: List[Exception] = []

        def keyboard_typist():
            try:
                # Type continuously in background
                keys = [ord('A'), ord('B'), ord('C'), 0x20, 0x0D, 0x08, ord('Z')]
                while not stop_event.is_set():
                    for vk in keys:
                        if stop_event.is_set():
                            break
                        InputInjector.press_key(vk, duration_s=0.001)
                        time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        typist_thread = threading.Thread(target=keyboard_typist, name="KeyboardTypistThread")
        typist_thread.start()

        try:
            # Send 20 rapid network lock and unlock cycles while typing storm is active
            for i in range(20):
                resp, _ = udp_client.lock()
                assert resp.get("status") in ("ok", "ignored")
                time.sleep(0.01)

                resp, _ = udp_client.unlock()
                assert resp.get("status") in ("ok", "ignored")
                time.sleep(0.01)

        finally:
            stop_event.set()
            typist_thread.join(timeout=3.0)

        assert not errors, f"Errors occurred during typing storm: {errors}"
        # Ensure final state is clean
        udp_client.unlock()
        time.sleep(0.05)
        assert not test_controller.is_locked

    def test_simultaneous_hotkey_press_while_network_packet_flood(self, test_controller: TestController):
        """Flood network listener with status/lock queries while operator triggers hotkeys."""
        udp_client = LockerUDPClient(port=test_controller.udp_port)
        osc_client = LockerOSCClient(port=test_controller.udp_port)
        stop_event = threading.Event()
        network_errors: List[Exception] = []

        def network_flooder():
            try:
                while not stop_event.is_set():
                    # Send mix of UDP status queries and OSC status queries
                    udp_client.status()
                    osc_client.status()
                    time.sleep(0.001)
            except Exception as e:
                network_errors.append(e)

        flooder_threads = [
            threading.Thread(target=network_flooder, name=f"Flooder-{i}")
            for i in range(4)
        ]
        for t in flooder_threads:
            t.start()

        try:
            # While network is flooded, trigger F11 and Unlock combo alternatingly
            for i in range(10):
                InputInjector.press_f11()
                time.sleep(0.05)
                assert test_controller.is_locked, f"F11 failed during network flood on iteration {i}"

                InputInjector.press_unlock_combo()
                time.sleep(0.05)
                assert not test_controller.is_locked, f"Unlock combo failed during network flood on iteration {i}"

        finally:
            stop_event.set()
            for t in flooder_threads:
                t.join(timeout=3.0)

        assert not network_errors, f"Network flooder encountered errors: {network_errors}"

    def test_simultaneous_dual_network_lock_and_unlock_race(self, test_controller: TestController):
        """Two independent network clients simultaneously fight for lock vs unlock state."""
        client_a = LockerTCPClient(port=test_controller.tcp_port)
        client_b = LockerUDPClient(port=test_controller.udp_port)
        stop_event = threading.Event()
        exceptions: List[Exception] = []

        def worker_a():
            try:
                for _ in range(30):
                    client_a.lock()
                    time.sleep(0.002)
                    client_a.unlock()
                    time.sleep(0.002)
            except Exception as e:
                exceptions.append(e)

        def worker_b():
            try:
                for _ in range(30):
                    client_b.unlock()
                    time.sleep(0.002)
                    client_b.lock()
                    time.sleep(0.002)
            except Exception as e:
                exceptions.append(e)

        ta = threading.Thread(target=worker_a)
        tb = threading.Thread(target=worker_b)
        ta.start()
        tb.start()
        ta.join(timeout=5.0)
        tb.join(timeout=5.0)

        assert not exceptions, f"Race condition threw exceptions: {exceptions}"
        # Ensure system settles cleanly
        client_a.unlock()
        time.sleep(0.05)
        assert not test_controller.is_locked
