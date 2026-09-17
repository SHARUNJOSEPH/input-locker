"""Tier 5 Adversarial: Network Fuzzing & Malformed Packet Injection.

Stress-tests:
1. UDP & OSC port fuzzing with truncated frames, null bytes, corrupt type tags, oversized datagrams (64KB).
2. TCP port fuzzing with fragmented streams, invalid JSON, 64KB non-delimited streams, abrupt disconnects.
3. Burst flood testing (1,000+ randomized datagrams).
4. Listener survivability: proves zero unhandled daemon crashes or listener dropouts.
"""

from __future__ import annotations

import os
import random
import socket
import struct
import time
import pytest
from typing import Tuple

from tests.conftest import TestController
from tests.harness.client_harness import LockerTCPClient, LockerUDPClient, LockerOSCClient
from input_locker.network.osc_handler import OSCHandler, decode_osc_packet, OSCDecodeError
from input_locker.network.tcp_handler import TCPHandler


class TestNetworkFuzzingAdversarial:
    """Fuzzing and penetration testing against network show control endpoints."""

    def test_udp_truncated_and_corrupt_packet_fuzzing(self, test_controller: TestController):
        """Inject an assortment of truncated, malformed, and corrupt UDP datagrams."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        dest = ("127.0.0.1", test_controller.udp_port)

        malformed_payloads = [
            b"",                                        # 0 bytes
            b"\x00",                                    # 1 null byte
            b"//",                                      # 2 bytes
            b"/a",                                      # 2 bytes
            b"#bun",                                    # 4 bytes truncated bundle header
            b"#bundle\x00\x00\x00\x00",                 # Truncated bundle timestamp
            b"#bundle\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\xff",  # Truncated element size
            b"/input_locker/lock\x00",                  # Address without 4-byte padding
            b"/input_locker/lock\x00\x00\x00\x00,\x00\x00\x00", # Missing type tag padding
            b"/input_locker/lock\x00\x00\x00\x00,z\x00\x00",     # Invalid type tag 'z'
            b"\x00" * 256,                              # 256 null bytes
            b"\xff" * 512,                              # 512 0xFF bytes
            b"{not valid json",                         # Malformed JSON
            b"{\"command\": ",                          # Truncated JSON
            b"{\"command\": null}",                     # Null command
            b"{\"cmd\": " + b"A" * 8192 + b"}",         # Oversized command string
        ]

        for payload in malformed_payloads:
            try:
                sock.sendto(payload, dest)
                time.sleep(0.001)
            except Exception as e:
                pytest.fail(f"Sending payload {payload[:16]!r} raised client exception: {e}")

        sock.close()

        # Verify listener is still alive and responds cleanly to valid request
        udp_client = LockerUDPClient(port=test_controller.udp_port)
        resp, rtt = udp_client.send_command("status", timeout=1.0)
        assert resp.get("status") == "ok", f"Server dropped out after UDP fuzzing! Response: {resp}"
        assert rtt < 100.0, f"RTT {rtt}ms exceeded 100ms budget post-fuzzing"

    def test_udp_64kb_oversized_frame_rejection(self, test_controller: TestController):
        """Send maximum legal UDP datagram size (65,507 bytes) filled with random data."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dest = ("127.0.0.1", test_controller.udp_port)

        huge_payload = os.urandom(65507)
        try:
            sock.sendto(huge_payload, dest)
        except OSError:
            # Some OS networking stacks reject jumbo datagrams at sendto; that is normal
            pass
        sock.close()

        time.sleep(0.05)
        # Verify server survives without crash
        udp_client = LockerUDPClient(port=test_controller.udp_port)
        resp, rtt = udp_client.send_command("status", timeout=1.0)
        assert resp.get("status") == "ok", "Server failed to respond after 64KB UDP frame"

    def test_udp_1000_random_garbage_packet_barrage(self, test_controller: TestController):
        """Flood UDP listener with 1,000 randomized byte sequences of lengths 1..2048."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dest = ("127.0.0.1", test_controller.udp_port)

        for _ in range(1000):
            sz = random.randint(1, 2048)
            garbage = os.urandom(sz)
            sock.sendto(garbage, dest)

        sock.close()
        time.sleep(0.05)

        # Confirm listener health and functionality
        udp_client = LockerUDPClient(port=test_controller.udp_port)
        resp, rtt = udp_client.lock()
        assert resp.get("status") == "ok"
        resp, rtt = udp_client.unlock()
        assert resp.get("status") == "ok"

    def test_tcp_fuzzing_and_stream_fragmentation(self, test_controller: TestController):
        """Fuzz TCP server with partial frames, huge lines, null bytes, and abrupt closes."""
        client = LockerTCPClient(port=test_controller.tcp_port)

        # 1. Send huge payload (65,536 bytes) without newline
        try:
            resp, rtt = client.send_raw(b"X" * 65536, timeout=0.5)
        except Exception:
            pass  # Server might close or time out on non-newline, which is acceptable

        # 2. Send 4096 null bytes followed by newline
        resp, rtt = client.send_raw(b"\x00" * 4096 + b"\n", timeout=1.0)
        # Verify response received (error or rejected)
        assert resp is not None

        # 3. Send malformed json
        resp, rtt = client.send_raw(b'{"command": "lock"\n', timeout=1.0)
        assert b"error" in resp.lower() or b"invalid" in resp.lower()

        # 4. Rapid client connect and immediately disconnect (30 cycles)
        for _ in range(30):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", test_controller.tcp_port))
            s.close()

        # 5. Verify server is still completely responsive
        resp_lock, rtt = client.lock()
        assert resp_lock.get("status") == "ok"
        resp_unlock, rtt = client.unlock()
        assert resp_unlock.get("status") == "ok"
        assert rtt < 100.0, f"TCP RTT {rtt}ms exceeded 100ms budget post-fuzzing"

    def test_osc_codec_pure_python_parser_fuzz_resilience(self):
        """Fuzz the pure-Python OSC codec directly with pathological byte sequences.
        
        Verifies that OSCDecodeError is raised gracefully with zero unhandled exceptions
        (e.g., IndexError, TypeError, MemoryError).
        """
        pathological_samples = [
            b"/",
            b"/a\x00",
            b"/test\x00\x00\x00,",
            b"/test\x00\x00\x00,i",
            b"/test\x00\x00\x00,i\x00\x00\x00",          # int tag with missing 4-byte payload
            b"/test\x00\x00\x00,s\x00\x00\x00hello",     # string tag with missing null term
            b"/test\x00\x00\x00,b\x00\x00\x00\x00\x00\x00\x10", # blob tag with truncated data
            b"/test\x00\x00\x00,b\x00\x00\x00\xff\xff\xff\xff", # blob tag with negative length
            b"#bundle\x00\x00\x00\x00\x00\x00\x00\x00\x01\x7f\xff\xff\xff", # bundle with huge element len
        ]

        for sample in pathological_samples:
            try:
                decode_osc_packet(sample)
            except OSCDecodeError:
                # Expected safe rejection
                pass
            except Exception as exc:
                pytest.fail(f"decode_osc_packet crashed with unexpected exception {type(exc).__name__}: {exc}")
