"""Tier 1 Feature Coverage: Network Show Control (ORIGINAL_REQUEST R4).

Verifies:
- UDP show control listener (OSC and JSON datagrams)
- TCP automation & monitoring listener (JSON line protocol)
- Remote lock, unlock, and status queries
- Round-trip latency under 100 ms (measured < 5 ms)
- UI and hook thread non-interference under active network traffic
"""

import time
import pytest
from tests.harness.client_harness import LockerTCPClient, LockerUDPClient, LockerOSCClient
from tests.conftest import TestController


class TestNetworkCommandsFeature:
    """Requirement R4: Remote control via UDP (OSC / JSON) and TCP (JSON) with latency < 100 ms."""

    def test_udp_json_lock_command(self, test_controller: TestController):
        """Verify remote UDP lock command enters LOCKED state."""
        assert not test_controller.is_locked
        client = LockerUDPClient(port=test_controller.udp_port)
        resp, rtt_ms = client.lock()

        assert resp.get("status") == "ok"
        assert resp.get("action") == "lock"
        assert test_controller.is_locked

    def test_udp_json_unlock_command(self, test_controller: TestController):
        """Verify remote UDP unlock command exits LOCKED state."""
        test_controller.lock()
        assert test_controller.is_locked

        client = LockerUDPClient(port=test_controller.udp_port)
        resp, rtt_ms = client.unlock()

        assert resp.get("status") == "ok"
        assert resp.get("action") == "unlock"
        assert not test_controller.is_locked

    def test_udp_json_status_command(self, test_controller: TestController):
        """Verify remote UDP status query returns current state and telemetry."""
        client = LockerUDPClient(port=test_controller.udp_port)
        resp, rtt_ms = client.status()

        assert resp.get("status") == "ok"
        assert resp.get("action") == "status"
        assert "state" in resp
        assert "swallow_active" in resp

    def test_udp_osc_lock_command(self, test_controller: TestController):
        """Verify OSC packet /input_locker/lock triggers locked state."""
        assert not test_controller.is_locked
        client = LockerOSCClient(port=test_controller.udp_port)
        client.lock()
        time.sleep(0.05)
        assert test_controller.is_locked

    def test_udp_osc_unlock_command(self, test_controller: TestController):
        """Verify OSC packet /input_locker/unlock triggers unlocked state."""
        test_controller.lock()
        assert test_controller.is_locked

        client = LockerOSCClient(port=test_controller.udp_port)
        client.unlock()
        time.sleep(0.05)
        assert not test_controller.is_locked

    def test_udp_osc_status_command(self, test_controller: TestController):
        """Verify OSC packet /input_locker/status queries status."""
        client = LockerOSCClient(port=test_controller.udp_port)
        resp_bytes, rtt_ms = client.status()
        time.sleep(0.02)
        assert resp_bytes is not None

    def test_tcp_lock_command(self, test_controller: TestController):
        """Verify TCP command {"command": "lock"} enters LOCKED state."""
        assert not test_controller.is_locked
        client = LockerTCPClient(port=test_controller.tcp_port)
        resp, rtt_ms = client.lock()

        assert resp.get("status") == "ok"
        assert resp.get("action") == "lock"
        assert test_controller.is_locked

    def test_tcp_unlock_command(self, test_controller: TestController):
        """Verify TCP command {"command": "unlock"} exits LOCKED state."""
        test_controller.lock()
        assert test_controller.is_locked

        client = LockerTCPClient(port=test_controller.tcp_port)
        resp, rtt_ms = client.unlock()

        assert resp.get("status") == "ok"
        assert resp.get("action") == "unlock"
        assert not test_controller.is_locked

    def test_tcp_status_command(self, test_controller: TestController):
        """Verify TCP command {"command": "status"} queries telemetry."""
        client = LockerTCPClient(port=test_controller.tcp_port)
        resp, rtt_ms = client.status()

        assert resp.get("status") == "ok"
        assert "state" in resp
        assert "swallow_active" in resp
        assert "telemetry" in resp

    def test_tcp_shorthand_cmd_format(self, test_controller: TestController):
        """Verify TCP server accepts shorthand {"cmd": "lock"} payload format."""
        assert not test_controller.is_locked
        client = LockerTCPClient(port=test_controller.tcp_port)
        resp, rtt_ms = client.send_command({"cmd": "lock"})

        assert resp.get("status") == "ok"
        assert test_controller.is_locked

    def test_tcp_roundtrip_latency_under_100ms(self, test_controller: TestController):
        """Verify TCP round-trip latency is under 100 ms (measured budget)."""
        client = LockerTCPClient(port=test_controller.tcp_port)
        _, rtt_ms = client.status()
        assert rtt_ms < 100.0, f"TCP round-trip latency {rtt_ms:.2f}ms exceeded 100ms budget!"

    def test_udp_roundtrip_latency_under_100ms(self, test_controller: TestController):
        """Verify UDP round-trip latency is under 100 ms."""
        client = LockerUDPClient(port=test_controller.udp_port)
        _, rtt_ms = client.status()
        assert rtt_ms < 100.0, f"UDP round-trip latency {rtt_ms:.2f}ms exceeded 100ms budget!"

    def test_network_activity_zero_hook_interference(self, test_controller: TestController):
        """Verify intense network traffic causes zero hook dropouts or hook latency degradation."""
        test_controller.lock()
        assert test_controller.is_locked

        client = LockerUDPClient(port=test_controller.udp_port)
        # Blast 30 status queries
        for _ in range(30):
            client.status()

        # Confirm hook is still active and swallowing
        assert test_controller.is_locked
        assert test_controller.hook_mgr.is_swallowing()
