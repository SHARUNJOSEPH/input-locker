"""Tier 2 Boundary Test Suite: Idempotency, Packet Malformation & Traffic Stress.

Verifies:
- Idempotent double-lock and double-unlock transitions
- Rapid back-to-back state machine transitions without race conditions
- Malformed JSON packets, empty lines, and unknown commands rejected safely
- Flood/burst traffic handling without listener stalls or hook dropouts
- TCP connection edge cases (immediate disconnect, rapid port reuse)
"""

import time
import socket
import json
import threading
import pytest
from tests.harness.client_harness import LockerTCPClient, LockerUDPClient
from tests.conftest import TestController


class TestIdempotentTransitionsBoundary:
    """Boundary Value Analysis: Idempotence, malformed packet tolerance, and network stress."""

    def test_double_lock_when_already_locked(self, test_controller: TestController):
        """Verify requesting lock when already locked returns gracefully without state corruption."""
        test_controller.lock()
        assert test_controller.is_locked

        client = LockerTCPClient(port=test_controller.tcp_port)
        resp, _ = client.lock()
        assert resp.get("status") in ("ok", "ignored")
        assert test_controller.is_locked

    def test_double_unlock_when_already_unlocked(self, test_controller: TestController):
        """Verify requesting unlock when already unlocked returns gracefully."""
        assert not test_controller.is_locked

        client = LockerTCPClient(port=test_controller.tcp_port)
        resp, _ = client.unlock()
        assert resp.get("status") in ("ok", "ignored")
        assert not test_controller.is_locked

    def test_rapid_alternating_lock_unlock(self, test_controller: TestController):
        """Verify 10 rapid alternating lock and unlock cycles execute with zero state drift."""
        client = LockerTCPClient(port=test_controller.tcp_port)
        for i in range(10):
            client.lock()
            assert test_controller.is_locked
            client.unlock()
            assert not test_controller.is_locked

    def test_malformed_json_packet_rejected(self, test_controller: TestController):
        """Verify malformed non-JSON data is rejected with an error without crashing server."""
        client = LockerTCPClient(port=test_controller.tcp_port)
        resp_raw, _ = client.send_raw(b"THIS_IS_CORRUPT_NOT_JSON\n")
        assert len(resp_raw) > 0
        resp_obj = json.loads(resp_raw.decode("utf-8").strip())
        assert resp_obj.get("status") in ("error", "unknown")

    def test_empty_packet_handling(self, test_controller: TestController):
        """Verify empty newline-only packets over TCP do not crash the reader."""
        client = LockerTCPClient(port=test_controller.tcp_port)
        # Send empty lines followed by a valid status query
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        try:
            s.connect(("127.0.0.1", test_controller.tcp_port))
            s.sendall(b"\n\n{\"command\": \"status\"}\n")
            resp = s.recv(2048)
            resp_obj = json.loads(resp.decode("utf-8").strip())
            assert resp_obj.get("status") == "ok"
        finally:
            s.close()

    def test_unknown_command_rejected(self, test_controller: TestController):
        """Verify unknown command string produces an error response rather than crashing."""
        client = LockerTCPClient(port=test_controller.tcp_port)
        resp, _ = client.send_command({"command": "self_destruct"})
        assert resp.get("status") == "error"

    def test_huge_payload_flood(self, test_controller: TestController):
        """Verify sending a 64 KB oversized payload is safely handled without buffer overflow."""
        client = LockerTCPClient(port=test_controller.tcp_port)
        giant_payload = (b"A" * 65536) + b"\n"
        resp_raw, _ = client.send_raw(giant_payload)
        time.sleep(0.02)

        # Confirm server remains fully functional
        resp, _ = client.status()
        assert resp.get("status") == "ok"

    def test_null_bytes_in_payload(self, test_controller: TestController):
        """Verify packet containing embedded null bytes is rejected gracefully."""
        client = LockerTCPClient(port=test_controller.tcp_port)
        resp_raw, _ = client.send_raw(b"{\"cmd\": \"lo\x00ck\"}\n")
        # Ensure server survives
        resp, _ = client.status()
        assert resp.get("status") == "ok"

    def test_case_variations_in_commands(self, test_controller: TestController):
        """Verify command parser accepts case variations ('LOCK', 'Lock', 'lOcK')."""
        assert not test_controller.is_locked
        client = LockerTCPClient(port=test_controller.tcp_port)

        resp, _ = client.send_command({"command": "LOCK"})
        assert test_controller.is_locked

        resp, _ = client.send_command({"command": "UnLoCk"})
        assert not test_controller.is_locked

    def test_extra_unexpected_json_fields(self, test_controller: TestController):
        """Verify JSON payloads with extraneous fields are accepted and parsed."""
        client = LockerTCPClient(port=test_controller.tcp_port)
        resp, _ = client.send_command({
            "command": "lock",
            "metadata": {"client": "test_runner", "version": "1.0"},
            "timestamp": time.time(),
        })
        assert resp.get("status") in ("ok", "ignored")
        assert test_controller.is_locked
        test_controller.unlock()

    def test_burst_status_queries(self, test_controller: TestController):
        """Verify 50 rapid-fire status queries over UDP return without socket loss."""
        client = LockerUDPClient(port=test_controller.udp_port)
        success_count = 0
        for _ in range(50):
            resp, _ = client.status()
            if resp.get("status") == "ok":
                success_count += 1

        assert success_count == 50, f"Expected 50 responses, got {success_count}"

    def test_partial_line_tcp_stream(self, test_controller: TestController):
        """Verify command delivered across multiple TCP packets is assembled properly."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", test_controller.tcp_port))
        try:
            # Send chunk 1
            s.sendall(b'{"command":')
            time.sleep(0.01)
            # Send chunk 2
            s.sendall(b' "lock"}\n')

            resp = s.recv(1024)
            resp_obj = json.loads(resp.decode("utf-8").strip())
            assert resp_obj.get("status") in ("ok", "ignored")
            assert test_controller.is_locked
        finally:
            s.close()
            test_controller.unlock()

    def test_client_disconnect_during_transmission(self, test_controller: TestController):
        """Verify client opening socket and disconnecting immediately causes zero server failure."""
        for _ in range(10):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", test_controller.tcp_port))
            s.close()

        # Confirm server still healthy
        client = LockerTCPClient(port=test_controller.tcp_port)
        resp, _ = client.status()
        assert resp.get("status") == "ok"

    def test_rapid_reconnect_cycles(self, test_controller: TestController):
        """Verify 20 back-to-back TCP connect-query-disconnect cycles reuse sockets cleanly."""
        client = LockerTCPClient(port=test_controller.tcp_port)
        for _ in range(20):
            resp, _ = client.status()
            assert resp.get("status") == "ok"

    def test_concurrent_multi_client_tcp(self, test_controller: TestController):
        """Verify 5 concurrent threads making TCP status requests simultaneously all succeed."""
        errors = []

        def worker():
            try:
                cl = LockerTCPClient(port=test_controller.tcp_port)
                for _ in range(5):
                    resp, _ = cl.status()
                    if resp.get("status") != "ok":
                        errors.append(f"Unexpected status: {resp}")
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)

        assert len(errors) == 0, f"Concurrent client errors: {errors}"
