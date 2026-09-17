"""High-precision network test clients for Windows AV Staging Input Locker.

Provides:
- LockerTCPClient: JSON-over-TCP command client with microsecond latency measurement
- LockerUDPClient: JSON-over-UDP show control client
- LockerOSCClient: OSC 1.0 UDP client for lighting/AV control console simulation (QLab, Companion)
"""

import socket
import time
import json
import struct
from typing import Dict, Any, Tuple, Optional


def encode_osc_message(address: str, *args) -> bytes:
    """Encodes an OSC 1.0 message packet according to the OSC 1.0 specification.
    
    OSC strings are null-terminated and padded with null bytes to a multiple of 4 bytes.
    """
    def pad4(b: bytes) -> bytes:
        pad_len = (4 - (len(b) % 4)) % 4
        if pad_len == 0:
            pad_len = 4
        return b + (b'\x00' * pad_len)

    addr_bytes = pad4(address.encode('utf-8'))
    
    # Build type tag
    type_tag = ","
    arg_payload = bytearray()
    for arg in args:
        if isinstance(arg, int):
            type_tag += "i"
            arg_payload.extend(struct.pack(">i", arg))
        elif isinstance(arg, float):
            type_tag += "f"
            arg_payload.extend(struct.pack(">f", arg))
        elif isinstance(arg, str):
            type_tag += "s"
            arg_payload.extend(pad4(arg.encode('utf-8')))
        else:
            raise ValueError(f"Unsupported OSC argument type: {type(arg)}")

    tag_bytes = pad4(type_tag.encode('utf-8'))
    return addr_bytes + tag_bytes + bytes(arg_payload)


class LockerTCPClient:
    """High-precision JSON-over-TCP test client."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9001, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def send_command(
        self,
        command: Any,
        timeout: Optional[float] = None,
    ) -> Tuple[Dict[str, Any], float]:
        """Sends a JSON or string command to the TCP server and measures round-trip latency in ms."""
        t_out = timeout if timeout is not None else self.timeout
        if isinstance(command, str):
            payload = json.dumps({"command": command, "cmd": command})
        elif isinstance(command, dict):
            payload = json.dumps(command)
        else:
            payload = str(command)

        data_bytes = (payload.strip() + "\n").encode("utf-8")

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(t_out)
        try:
            t0 = time.perf_counter()
            s.connect((self.host, self.port))
            s.sendall(data_bytes)
            
            # Read response until newline or EOF
            chunks = []
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
            t1 = time.perf_counter()
            rtt_ms = (t1 - t0) * 1000.0

            raw_resp = b"".join(chunks).decode("utf-8", errors="replace").strip()
            if not raw_resp:
                return ({"status": "error", "message": "empty response"}, rtt_ms)
            try:
                resp_obj = json.loads(raw_resp)
            except json.JSONDecodeError:
                resp_obj = {"raw": raw_resp, "status": "unknown"}
            return (resp_obj, round(rtt_ms, 3))
        finally:
            try:
                s.close()
            except Exception:
                pass

    def send_raw(self, raw_data: bytes, timeout: Optional[float] = None) -> Tuple[bytes, float]:
        """Sends raw bytes over TCP without framing, measuring response latency."""
        t_out = timeout if timeout is not None else self.timeout
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(t_out)
        try:
            t0 = time.perf_counter()
            s.connect((self.host, self.port))
            s.sendall(raw_data)
            resp = s.recv(4096)
            t1 = time.perf_counter()
            return (resp, (t1 - t0) * 1000.0)
        finally:
            try:
                s.close()
            except Exception:
                pass

    def lock(self) -> Tuple[Dict[str, Any], float]:
        return self.send_command({"command": "lock", "cmd": "lock"})

    def unlock(self) -> Tuple[Dict[str, Any], float]:
        return self.send_command({"command": "unlock", "cmd": "unlock"})

    def status(self) -> Tuple[Dict[str, Any], float]:
        return self.send_command({"command": "status", "cmd": "status"})


class LockerUDPClient:
    """High-precision JSON-over-UDP show control client."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9000, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def send_command(
        self,
        command: Any,
        timeout: Optional[float] = None,
    ) -> Tuple[Dict[str, Any], float]:
        """Sends a JSON command over UDP and measures round-trip response latency."""
        t_out = timeout if timeout is not None else self.timeout
        if isinstance(command, str):
            payload = json.dumps({"command": command, "cmd": command})
        elif isinstance(command, dict):
            payload = json.dumps(command)
        else:
            payload = str(command)

        data_bytes = payload.encode("utf-8")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(t_out)
        try:
            t0 = time.perf_counter()
            s.sendto(data_bytes, (self.host, self.port))
            data, _ = s.recvfrom(4096)
            t1 = time.perf_counter()
            rtt_ms = (t1 - t0) * 1000.0

            text = data.decode("utf-8", errors="replace").strip()
            try:
                resp_obj = json.loads(text)
            except json.JSONDecodeError:
                resp_obj = {"raw": text, "status": "unknown"}
            return (resp_obj, round(rtt_ms, 3))
        finally:
            try:
                s.close()
            except Exception:
                pass

    def send_raw(self, raw_data: bytes, timeout: Optional[float] = None) -> Tuple[bytes, float]:
        t_out = timeout if timeout is not None else self.timeout
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(t_out)
        try:
            t0 = time.perf_counter()
            s.sendto(raw_data, (self.host, self.port))
            data, _ = s.recvfrom(4096)
            t1 = time.perf_counter()
            return (data, (t1 - t0) * 1000.0)
        finally:
            try:
                s.close()
            except Exception:
                pass

    def lock(self) -> Tuple[Dict[str, Any], float]:
        return self.send_command({"command": "lock", "cmd": "lock"})

    def unlock(self) -> Tuple[Dict[str, Any], float]:
        return self.send_command({"command": "unlock", "cmd": "unlock"})

    def status(self) -> Tuple[Dict[str, Any], float]:
        return self.send_command({"command": "status", "cmd": "status"})


class LockerOSCClient:
    """Standard OSC 1.0 UDP client for AV show control (Resolume / QLab / Companion)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9000, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def send_osc(
        self,
        address: str,
        *args,
        timeout: Optional[float] = None,
        expect_response: bool = True,
    ) -> Tuple[Optional[bytes], float]:
        t_out = timeout if timeout is not None else self.timeout
        osc_bytes = encode_osc_message(address, *args)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(t_out)
        try:
            t0 = time.perf_counter()
            s.sendto(osc_bytes, (self.host, self.port))
            resp_bytes = None
            if expect_response:
                try:
                    resp_bytes, _ = s.recvfrom(4096)
                except socket.timeout:
                    resp_bytes = None
            t1 = time.perf_counter()
            rtt_ms = (t1 - t0) * 1000.0
            return (resp_bytes, round(rtt_ms, 3))
        finally:
            try:
                s.close()
            except Exception:
                pass

    def lock(self) -> Tuple[Optional[bytes], float]:
        return self.send_osc("/input_locker/lock")

    def unlock(self) -> Tuple[Optional[bytes], float]:
        return self.send_osc("/input_locker/unlock")

    def status(self) -> Tuple[Optional[bytes], float]:
        return self.send_osc("/input_locker/status")
