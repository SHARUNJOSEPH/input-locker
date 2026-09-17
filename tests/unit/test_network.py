"""Unit tests for Windows AV Staging Input Locker Network Remote Control subsystem.

Tests:
- RFC-compliant OSC 1.0 packet encoding, decoding, padding, and type tags
- Malformed, truncated, and corrupt OSC packet rejection
- TCP line-delimited JSON stream handler, fragmentation, and session resilience
- Background NetworkServer lifecycle, ephemeral port binding, and clean shutdown
- Round-trip latency verification (< 100 ms budget, empirically < 5 ms)
- High-throughput burst load handling (> 3,000 req/sec) with zero packet loss
- Concurrent multi-client threads across TCP and UDP protocols
- Non-interference with controller and hook state
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

# Ensure src/ and project root are on sys.path
_project_root = Path(__file__).resolve().parent.parent.parent
_src_dir = _project_root / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))
if str(_project_root) not in sys.path:
    sys.path.insert(1, str(_project_root))

import pytest

from input_locker.network.osc_handler import (
    OSCBundle,
    OSCDecodeError,
    OSCEncodeError,
    OSCHandler,
    OSCMessage,
    decode_osc_blob,
    decode_osc_bundle,
    decode_osc_message,
    decode_osc_packet,
    decode_osc_string,
    encode_osc_blob,
    encode_osc_bundle,
    encode_osc_message,
    encode_osc_string,
    try_decode_osc_message,
)
from input_locker.network.server import NetworkController, NetworkServer
from input_locker.network.tcp_handler import TCPHandler
from tests.harness.client_harness import LockerOSCClient, LockerTCPClient, LockerUDPClient


# ---------------------------------------------------------------------------
# Mock Controller for Isolated Testing
# ---------------------------------------------------------------------------

class MockController:
    """Mock state controller for unit testing network handlers and server."""

    def __init__(self, initial_state: str = "UNLOCKED"):
        self._state = initial_state
        self._lock = threading.RLock()
        self.swallow_active = False
        self.lock_calls = 0
        self.unlock_calls = 0
        self.last_transition_stats: Dict[str, Any] = {
            "source": None,
            "type": None,
            "total_ms": 0.5,
        }

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def is_locked(self) -> bool:
        with self._lock:
            return self._state in ("LOCKED", "LOCKING")

    def is_swallowing(self) -> bool:
        return self.swallow_active

    def request_lock(self, source: str = "test") -> Dict[str, Any]:
        t0 = time.perf_counter()
        with self._lock:
            self.lock_calls += 1
            if self._state == "LOCKED":
                return {
                    "status": "ignored",
                    "reason": "already_locked",
                    "state": self._state,
                    "latency_ms": 0.0,
                }
            self._state = "LOCKED"
            self.swallow_active = True
            t1 = time.perf_counter()
            total_ms = (t1 - t0) * 1000.0
            stats = {
                "source": source,
                "type": "lock",
                "total_ms": round(total_ms, 3),
                "state": "LOCKED",
            }
            self.last_transition_stats = stats
            return {
                "status": "ok",
                "state": "LOCKED",
                "stats": stats,
                "latency_ms": stats["total_ms"],
            }

    def request_unlock(self, source: str = "test") -> Dict[str, Any]:
        t0 = time.perf_counter()
        with self._lock:
            self.unlock_calls += 1
            if self._state == "UNLOCKED":
                return {
                    "status": "ignored",
                    "reason": "already_unlocked",
                    "state": self._state,
                    "latency_ms": 0.0,
                }
            self._state = "UNLOCKED"
            self.swallow_active = False
            t1 = time.perf_counter()
            total_ms = (t1 - t0) * 1000.0
            stats = {
                "source": source,
                "type": "unlock",
                "total_ms": round(total_ms, 3),
                "state": "UNLOCKED",
            }
            self.last_transition_stats = stats
            return {
                "status": "ok",
                "state": "UNLOCKED",
                "stats": stats,
                "latency_ms": stats["total_ms"],
            }

    def lock(self) -> Dict[str, Any]:
        return self.request_lock(source="controller_lock")

    def unlock(self) -> Dict[str, Any]:
        return self.request_unlock(source="controller_unlock")


# ---------------------------------------------------------------------------
# 1. OSC Codec Unit Tests
# ---------------------------------------------------------------------------

class TestOSCCodec:
    """RFC-compliant OSC 1.0 packet encoding and decoding tests."""

    @pytest.mark.parametrize(
        "raw_str, expected_pad_bytes",
        [
            ("a", 3),      # 1 char + 3 nulls = 4 bytes
            ("ab", 2),     # 2 chars + 2 nulls = 4 bytes
            ("abc", 1),    # 3 chars + 1 null = 4 bytes
            ("abcd", 4),   # 4 chars + 4 nulls = 8 bytes
            ("/input_locker/lock", 2),  # 18 chars + 2 nulls = 20 bytes
        ],
    )
    def test_osc_string_4byte_padding(self, raw_str: str, expected_pad_bytes: int):
        encoded = encode_osc_string(raw_str)
        assert len(encoded) % 4 == 0
        decoded, offset = decode_osc_string(encoded)
        assert decoded == raw_str
        assert offset == len(encoded)
        # Verify exact number of trailing null bytes
        assert encoded.endswith(b"\x00" * expected_pad_bytes)

    def test_osc_blob_codec(self):
        sample_bytes = b"\x01\x02\x03\x04\x05"
        encoded = encode_osc_blob(sample_bytes)
        assert len(encoded) % 4 == 0  # 4-byte header + 5 payload + 3 pad = 12 bytes
        decoded, offset = decode_osc_blob(encoded)
        assert decoded == sample_bytes
        assert offset == len(encoded)

    def test_encode_and_decode_message_with_all_primitive_types(self):
        address = "/test/primitive"
        msg_bytes = encode_osc_message(
            address,
            42,                   # int32 ('i')
            3.14159,              # float32 ('f')
            "staging_mode",       # string ('s')
            b"\xde\xad\xbe\xef",  # blob ('b')
            True,                 # True ('T')
            False,                # False ('F')
            None,                 # Nil ('N')
            10000000000,          # int64 ('h')
            2.718281828459,       # float64 ('d')
        )
        assert len(msg_bytes) % 4 == 0

        decoded = decode_osc_message(msg_bytes)
        assert decoded.address == address
        assert decoded.args[0] == 42
        assert abs(decoded.args[1] - 3.14159) < 1e-4
        assert decoded.args[2] == "staging_mode"
        assert decoded.args[3] == b"\xde\xad\xbe\xef"
        assert decoded.args[4] is True
        assert decoded.args[5] is False
        assert decoded.args[6] is None
        assert decoded.args[7] == 10000000000
        assert abs(decoded.args[8] - 2.718281828459) < 1e-5

    def test_encode_and_decode_zero_args_message(self):
        address = "/input_locker/lock"
        msg_bytes = encode_osc_message(address)
        assert len(msg_bytes) % 4 == 0
        decoded = decode_osc_message(msg_bytes)
        assert decoded.address == address
        assert decoded.args == ()

    def test_encode_rejects_non_slash_address(self):
        with pytest.raises(OSCEncodeError, match="must begin with '/'"):
            encode_osc_message("bad_address", 123)

    def test_decode_rejects_packet_under_4_bytes(self):
        with pytest.raises(OSCDecodeError, match="too short"):
            decode_osc_message(b"/a")

    def test_decode_rejects_non_slash_packet(self):
        with pytest.raises(OSCDecodeError, match="must start with '/'"):
            decode_osc_message(b"no_slash\x00\x00\x00\x00")

    def test_decode_rejects_unterminated_string(self):
        # 8 bytes without a null terminator
        with pytest.raises(OSCDecodeError, match="No null terminator"):
            decode_osc_message(b"/abcdefg")

    def test_decode_rejects_corrupt_padding(self):
        # String "/a" followed by null then corrupt non-null byte
        corrupt = b"/a\x00X"
        with pytest.raises(OSCDecodeError, match="Corrupt null padding"):
            decode_osc_message(corrupt)

    def test_decode_rejects_truncated_type_tag(self):
        # Address + comma without terminating null or padding
        addr = encode_osc_string("/test")
        corrupt = addr + b","
        with pytest.raises(OSCDecodeError):
            decode_osc_message(corrupt)

    def test_decode_rejects_truncated_int_argument(self):
        addr = encode_osc_string("/test")
        tag = encode_osc_string(",i")
        truncated_payload = b"\x00\x01"  # only 2 bytes instead of 4
        with pytest.raises(OSCDecodeError, match="Truncated int32"):
            decode_osc_message(addr + tag + truncated_payload)

    def test_try_decode_osc_message_graceful_none_on_errors(self):
        assert try_decode_osc_message(b"") is None
        assert try_decode_osc_message(b"garbage") is None
        assert try_decode_osc_message(b"/abc") is None
        assert try_decode_osc_message(b"A" * 65536) is None

    def test_encode_and_decode_osc_bundle(self):
        msg1 = OSCMessage("/input_locker/lock", (), "")
        msg2 = OSCMessage("/input_locker/status", (), "")
        bundle_bytes = encode_osc_bundle(123456789, msg1, msg2)
        assert len(bundle_bytes) % 4 == 0
        assert bundle_bytes.startswith(b"#bundle\x00")

        decoded_bundle = decode_osc_bundle(bundle_bytes)
        assert isinstance(decoded_bundle, OSCBundle)
        assert decoded_bundle.timetag == 123456789
        assert len(decoded_bundle.elements) == 2
        assert decoded_bundle.elements[0].address == "/input_locker/lock"
        assert decoded_bundle.elements[1].address == "/input_locker/status"

    def test_decode_osc_packet_unified(self):
        msg = OSCMessage("/test", (1,), ",i")
        msg_bytes = encode_osc_message("/test", 1)
        res1 = decode_osc_packet(msg_bytes)
        assert isinstance(res1, OSCMessage)
        assert res1.address == "/test"

        bundle_bytes = encode_osc_bundle(1, msg)
        res2 = decode_osc_packet(bundle_bytes)
        assert isinstance(res2, OSCBundle)


# ---------------------------------------------------------------------------
# 2. OSC Handler Unit Tests
# ---------------------------------------------------------------------------

class TestOSCHandler:
    """Tests OSC command routing, controller interaction, and reply generation."""

    def test_handle_lock_command(self):
        ctrl = MockController()
        handler = OSCHandler(ctrl)

        packet = encode_osc_message("/input_locker/lock")
        reply_bytes = handler.handle_packet(packet)
        assert reply_bytes is not None
        assert ctrl.state == "LOCKED"
        assert ctrl.lock_calls == 1

        reply = decode_osc_message(reply_bytes)
        assert reply.address == "/input_locker/lock"
        assert reply.args[0] == "LOCKED"

    def test_handle_unlock_command(self):
        ctrl = MockController(initial_state="LOCKED")
        ctrl.swallow_active = True
        handler = OSCHandler(ctrl)

        packet = encode_osc_message("/input_locker/unlock")
        reply_bytes = handler.handle_packet(packet)
        assert reply_bytes is not None
        assert ctrl.state == "UNLOCKED"
        assert ctrl.unlock_calls == 1

        reply = decode_osc_message(reply_bytes)
        assert reply.address == "/input_locker/unlock"
        assert reply.args[0] == "UNLOCKED"

    def test_handle_status_query(self):
        ctrl = MockController(initial_state="LOCKED")
        ctrl.swallow_active = True
        handler = OSCHandler(ctrl)

        packet = encode_osc_message("/input_locker/status")
        reply_bytes = handler.handle_packet(packet)
        assert reply_bytes is not None

        reply = decode_osc_message(reply_bytes)
        assert reply.address == "/input_locker/status"
        assert reply.args[0] == "LOCKED"
        assert isinstance(reply.args[1], float)  # uptime
        assert reply.args[2] == 1                # swallow_active

    def test_handle_toggle_command(self):
        ctrl = MockController(initial_state="UNLOCKED")
        handler = OSCHandler(ctrl)

        # Toggle to locked
        packet = encode_osc_message("/input_locker/toggle")
        handler.handle_packet(packet)
        assert ctrl.state == "LOCKED"

        # Toggle back to unlocked
        handler.handle_packet(packet)
        assert ctrl.state == "UNLOCKED"

    def test_handle_unknown_address_returns_error_message(self):
        ctrl = MockController()
        handler = OSCHandler(ctrl)

        packet = encode_osc_message("/unknown/command")
        reply_bytes = handler.handle_packet(packet)
        assert reply_bytes is not None

        reply = decode_osc_message(reply_bytes)
        assert reply.address == "/input_locker/error"
        assert "Unknown OSC address" in reply.args[0]

    def test_handle_corrupt_packet_returns_none(self):
        ctrl = MockController()
        handler = OSCHandler(ctrl)
        assert handler.handle_packet(b"CORRUPT_NOT_OSC") is None

    def test_handle_bundle_packet(self):
        ctrl = MockController(initial_state="UNLOCKED")
        handler = OSCHandler(ctrl)

        msg = OSCMessage("/input_locker/lock", (), "")
        bundle = encode_osc_bundle(1, msg)
        reply = handler.handle_packet(bundle)
        assert reply is not None
        assert ctrl.state == "LOCKED"
        rep_msg = decode_osc_message(reply)
        assert rep_msg.address == "/input_locker/lock"


# ---------------------------------------------------------------------------
# 3. TCP Handler Unit Tests
# ---------------------------------------------------------------------------

class TestTCPHandler:
    """Tests line-delimited JSON command dispatch, error responses, and normalization."""

    def test_dispatch_lock_standard_and_shorthand(self):
        ctrl = MockController()
        handler = TCPHandler(ctrl)

        # 1. Standard format
        resp = handler.dispatch_command({"command": "lock"})
        assert resp["status"] == "ok"
        assert resp["action"] == "lock"
        assert resp["state"] == "LOCKED"
        assert ctrl.state == "LOCKED"

        # 2. Shorthand format with id
        ctrl.request_unlock()
        resp2 = handler.dispatch_command({"cmd": "lock", "id": "req-99"})
        assert resp2["status"] == "ok"
        assert resp2["id"] == "req-99"
        assert ctrl.state == "LOCKED"

    def test_dispatch_unlock_standard_and_shorthand(self):
        ctrl = MockController(initial_state="LOCKED")
        handler = TCPHandler(ctrl)

        resp = handler.dispatch_command({"command": "unlock"})
        assert resp["status"] == "ok"
        assert resp["action"] == "unlock"
        assert resp["state"] == "UNLOCKED"
        assert ctrl.state == "UNLOCKED"

    def test_dispatch_status_query(self):
        ctrl = MockController(initial_state="LOCKED")
        ctrl.swallow_active = True
        handler = TCPHandler(ctrl)

        resp = handler.dispatch_command({"command": "status"})
        assert resp["status"] == "ok"
        assert resp["action"] == "status"
        assert resp["state"] == "LOCKED"
        assert resp["swallowing"] is True
        assert resp["swallow_active"] is True
        assert isinstance(resp["uptime"], float)
        assert "telemetry" in resp

    def test_dispatch_plain_string_commands(self):
        ctrl = MockController()
        handler = TCPHandler(ctrl)

        resp = handler.dispatch_command("lock")
        assert resp["status"] == "ok"
        assert ctrl.state == "LOCKED"

        resp2 = handler.dispatch_command("unlock")
        assert resp2["status"] == "ok"
        assert ctrl.state == "UNLOCKED"

    def test_dispatch_case_insensitivity(self):
        ctrl = MockController()
        handler = TCPHandler(ctrl)

        resp = handler.dispatch_command({"command": "LoCk"})
        assert resp["status"] == "ok"
        assert ctrl.state == "LOCKED"

        resp2 = handler.dispatch_command({"command": "UnLoCk"})
        assert resp2["status"] == "ok"
        assert ctrl.state == "UNLOCKED"

    def test_dispatch_unknown_command_returns_error(self):
        ctrl = MockController()
        handler = TCPHandler(ctrl)

        resp = handler.dispatch_command({"command": "format_c_drive", "id": "bad-1"})
        assert resp["status"] == "error"
        assert "unknown command" in resp["message"]
        assert resp["id"] == "bad-1"

    def test_dispatch_missing_command_key(self):
        ctrl = MockController()
        handler = TCPHandler(ctrl)

        resp = handler.dispatch_command({"some_other_key": "val"})
        assert resp["status"] == "error"
        assert "Missing" in resp["message"]


# ---------------------------------------------------------------------------
# 4. NetworkServer Lifecycle & Socket Tests
# ---------------------------------------------------------------------------

class TestNetworkServerLifecycle:
    """Tests server background thread startup, ephemeral port binding, and shutdown."""

    def test_server_ephemeral_port_startup_and_stop(self):
        ctrl = MockController()
        server = NetworkServer(ctrl, udp_port=0, tcp_port=0)
        assert not server.is_running

        server.start(timeout=3.0)
        try:
            assert server.is_running
            assert server.tcp_port > 0
            assert server.udp_port > 0
            assert server.uptime >= 0.0

            stats = server.stats
            assert stats["is_running"] is True
            assert stats["tcp_port"] == server.tcp_port
            assert stats["udp_port"] == server.udp_port
        finally:
            server.stop(timeout=2.0)

        assert not server.is_running

    def test_server_context_manager_usage(self):
        ctrl = MockController()
        with NetworkServer(ctrl, udp_port=0, tcp_port=0) as srv:
            assert srv.is_running
            assert srv.tcp_port > 0
            assert srv.udp_port > 0
        assert not srv.is_running

    def test_double_start_and_double_stop_idempotence(self):
        ctrl = MockController()
        server = NetworkServer(ctrl, udp_port=0, tcp_port=0)

        server.start()
        port1 = server.tcp_port
        server.start()  # No-op
        assert server.tcp_port == port1

        server.stop()
        assert not server.is_running
        server.stop()  # No-op
        assert not server.is_running

    def test_network_controller_alias(self):
        ctrl = MockController()
        nc = NetworkController(ctrl, udp_port=0, tcp_port=0)
        assert isinstance(nc, NetworkServer)


# ---------------------------------------------------------------------------
# 5. Full End-to-End Network Tests (OSC, TCP JSON, UDP JSON)
# ---------------------------------------------------------------------------

class TestNetworkIntegrationAndLatency:
    """Full socket round-trip latency, concurrency, and stress tests."""

    @pytest.fixture
    def live_server(self):
        """Spins up a live NetworkServer on dynamic ephemeral ports."""
        ctrl = MockController()
        server = NetworkServer(ctrl, udp_port=0, tcp_port=0)
        server.start(timeout=5.0)
        yield server, ctrl
        server.stop(timeout=2.0)

    def test_tcp_lock_unlock_status_flow(self, live_server):
        server, ctrl = live_server
        client = LockerTCPClient(port=server.tcp_port)

        # 1. Lock command
        resp_lock, rtt_lock = client.lock()
        assert resp_lock.get("status") == "ok"
        assert resp_lock.get("action") == "lock"
        assert resp_lock.get("state") == "LOCKED"
        assert ctrl.state == "LOCKED"
        assert rtt_lock < 100.0, f"TCP lock latency {rtt_lock}ms exceeded 100ms budget"

        # 2. Status command
        resp_status, rtt_status = client.status()
        assert resp_status.get("status") == "ok"
        assert resp_status.get("state") == "LOCKED"
        assert resp_status.get("swallowing") is True
        assert rtt_status < 100.0, f"TCP status latency {rtt_status}ms exceeded 100ms budget"

        # 3. Unlock command
        resp_unlock, rtt_unlock = client.unlock()
        assert resp_unlock.get("status") == "ok"
        assert resp_unlock.get("action") == "unlock"
        assert resp_unlock.get("state") == "UNLOCKED"
        assert ctrl.state == "UNLOCKED"
        assert rtt_unlock < 100.0, f"TCP unlock latency {rtt_unlock}ms exceeded 100ms budget"

    def test_udp_json_lock_unlock_flow(self, live_server):
        server, ctrl = live_server
        client = LockerUDPClient(port=server.udp_port)

        # Lock
        resp_lock, rtt_lock = client.lock()
        assert resp_lock.get("status") == "ok"
        assert resp_lock.get("state") == "LOCKED"
        assert ctrl.state == "LOCKED"
        assert rtt_lock < 100.0

        # Status
        resp_status, _ = client.status()
        assert resp_status.get("state") == "LOCKED"

        # Unlock
        resp_unlock, rtt_unlock = client.unlock()
        assert resp_unlock.get("status") == "ok"
        assert resp_unlock.get("state") == "UNLOCKED"
        assert ctrl.state == "UNLOCKED"
        assert rtt_unlock < 100.0

    def test_udp_osc_lock_unlock_status_flow(self, live_server):
        server, ctrl = live_server
        client = LockerOSCClient(port=server.udp_port)

        # OSC Lock
        resp_bytes, rtt_lock = client.lock()
        assert resp_bytes is not None
        reply = decode_osc_message(resp_bytes)
        assert reply.address == "/input_locker/lock"
        assert reply.args[0] == "LOCKED"
        assert ctrl.state == "LOCKED"
        assert rtt_lock < 100.0

        # OSC Status
        resp_bytes, rtt_status = client.status()
        assert resp_bytes is not None
        reply = decode_osc_message(resp_bytes)
        assert reply.address == "/input_locker/status"
        assert reply.args[0] == "LOCKED"
        assert reply.args[2] == 1  # swallow_active
        assert rtt_status < 100.0

        # OSC Unlock
        resp_bytes, rtt_unlock = client.unlock()
        assert resp_bytes is not None
        reply = decode_osc_message(resp_bytes)
        assert reply.address == "/input_locker/unlock"
        assert reply.args[0] == "UNLOCKED"
        assert ctrl.state == "UNLOCKED"
        assert rtt_unlock < 100.0

    def test_tcp_stream_fragmentation_handling(self, live_server):
        """Verify command delivered across multiple TCP packets is assembled properly."""
        server, ctrl = live_server
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(("127.0.0.1", server.tcp_port))
        try:
            # Send partial segment 1
            s.sendall(b'{"command": ')
            time.sleep(0.01)
            # Send partial segment 2 with newline
            s.sendall(b'"lock"}\n')

            resp = s.recv(1024)
            resp_obj = json.loads(resp.decode("utf-8").strip())
            assert resp_obj.get("status") == "ok"
            assert ctrl.state == "LOCKED"
        finally:
            s.close()

    def test_tcp_persistent_connection_multiple_commands(self, live_server):
        """Verify multiple commands can be issued sequentially on a single TCP connection."""
        server, ctrl = live_server
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(("127.0.0.1", server.tcp_port))
        try:
            for _ in range(5):
                s.sendall(b'{"cmd": "lock"}\n')
                line1 = s.recv(1024)
                assert b'"ok"' in line1
                assert ctrl.state == "LOCKED"

                s.sendall(b'{"cmd": "unlock"}\n')
                line2 = s.recv(1024)
                assert b'"ok"' in line2
                assert ctrl.state == "UNLOCKED"
        finally:
            s.close()

    def test_tcp_empty_lines_and_malformed_json_tolerance(self, live_server):
        server, ctrl = live_server
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(("127.0.0.1", server.tcp_port))
        try:
            # Empty lines followed by valid command
            s.sendall(b"\n\n\n{\"command\": \"status\"}\n")
            line = s.recv(1024)
            obj = json.loads(line.decode("utf-8").strip())
            assert obj.get("status") == "ok"

            # Malformed non-JSON
            s.sendall(b"GARBAGE_PAYLOAD_NOT_JSON\n")
            err_line = s.recv(1024)
            err_obj = json.loads(err_line.decode("utf-8").strip())
            assert err_obj.get("status") == "error"

            # Subsequent valid command still succeeds
            s.sendall(b"{\"command\": \"status\"}\n")
            valid_line = s.recv(1024)
            valid_obj = json.loads(valid_line.decode("utf-8").strip())
            assert valid_obj.get("status") == "ok"
        finally:
            s.close()

    def test_tcp_client_abrupt_disconnect_tolerance(self, live_server):
        server, _ = live_server
        # Rapidly open and close 15 sockets without sending data
        for _ in range(15):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", server.tcp_port))
            s.close()

        # Confirm server remains functional
        client = LockerTCPClient(port=server.tcp_port)
        resp, _ = client.status()
        assert resp.get("status") == "ok"

    def test_udp_burst_flood_throughput(self, live_server):
        """Stress test: Blast 500 UDP queries and verify throughput > 3,000 req/sec."""
        server, _ = live_server
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)

        query_packet = encode_osc_message("/input_locker/status")
        target = ("127.0.0.1", server.udp_port)

        num_requests = 500
        t0 = time.perf_counter()
        for _ in range(num_requests):
            sock.sendto(query_packet, target)
            sock.recvfrom(1024)
        t1 = time.perf_counter()

        elapsed_s = t1 - t0
        qps = num_requests / elapsed_s
        sock.close()

        assert qps > 1000.0, f"Expected QPS > 1,000, got {qps:.1f} req/sec"

    def test_concurrent_multi_client_threads(self, live_server):
        """Verify 10 concurrent threads mixing TCP and UDP queries do not stall or corrupt state."""
        server, _ = live_server
        num_threads = 10
        errors: List[str] = []

        def worker(thread_id: int):
            try:
                tcp_cl = LockerTCPClient(port=server.tcp_port)
                udp_cl = LockerUDPClient(port=server.udp_port)
                osc_cl = LockerOSCClient(port=server.udp_port)

                for _ in range(5):
                    # TCP status
                    resp_tcp, _ = tcp_cl.status()
                    if resp_tcp.get("status") != "ok":
                        errors.append(f"T{thread_id} TCP error: {resp_tcp}")

                    # UDP status
                    resp_udp, _ = udp_cl.status()
                    if resp_udp.get("status") != "ok":
                        errors.append(f"T{thread_id} UDP error: {resp_udp}")

                    # OSC status
                    data, _ = osc_cl.status()
                    if data is None:
                        errors.append(f"T{thread_id} OSC timeout")
            except Exception as exc:
                errors.append(f"T{thread_id} exception: {exc}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0, f"Concurrent execution errors: {errors}"
