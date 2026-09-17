"""Pure-Python RFC-compliant Open Sound Control (OSC 1.0) packet codec and handler.

Provides zero-dependency encoding, decoding, and dispatching of OSC 1.0
messages and bundles for AV staging show controllers (e.g. QLab, Bitfocus
Companion, Resolume Arena, grandMA).

OSC 1.0 Specification Compliance:
- 32-bit (4-byte) alignment for all strings, type tags, and binary data
- Null-terminated strings padded with 1 to 4 null bytes to multiple of 4
- Standard atomic types: 'i' (int32), 'f' (float32), 's' (string), 'b' (blob)
- Extended types: 'h' (int64), 'd' (float64), 'T' (True), 'F' (False), 'N' (Nil)
- OSC Bundles starting with '#bundle\x00' with 64-bit NTP timestamp
- Safe exception handling with zero unhandled crashes on malformed data
"""

from __future__ import annotations

import dataclasses
import struct
import time
from typing import Any, List, Optional, Tuple, Union


class OSCError(Exception):
    """Base exception for OSC codec errors."""
    pass


class OSCDecodeError(OSCError):
    """Raised when an OSC packet cannot be decoded due to formatting errors."""
    pass


class OSCEncodeError(OSCError):
    """Raised when an OSC packet cannot be encoded."""
    pass


@dataclasses.dataclass(frozen=True)
class OSCMessage:
    """Represents a decoded OSC 1.0 message."""
    address: str
    args: Tuple[Any, ...]
    type_tags: str

    def __repr__(self) -> str:
        return f"OSCMessage(address={self.address!r}, args={self.args!r}, type_tags={self.type_tags!r})"


@dataclasses.dataclass(frozen=True)
class OSCBundle:
    """Represents a decoded OSC 1.0 bundle."""
    timetag: int
    elements: Tuple[Union[OSCMessage, OSCBundle], ...]

    def __repr__(self) -> str:
        return f"OSCBundle(timetag={self.timetag}, elements_count={len(self.elements)})"


def _pad4(b: bytes) -> bytes:
    """Pads bytes with null characters (1 to 4) so length is a multiple of 4."""
    pad_len = 4 - (len(b) % 4)
    return b + (b"\x00" * pad_len)


def encode_osc_string(s: str) -> bytes:
    """Encodes a string as a null-terminated, 4-byte aligned OSC-string."""
    raw = s.encode("utf-8")
    return _pad4(raw)


def decode_osc_string(data: bytes, offset: int = 0) -> Tuple[str, int]:
    """Decodes an OSC-string from data at offset.
    
    Returns (string, new_offset).
    Raises OSCDecodeError if string is malformed or truncated.
    """
    if offset >= len(data):
        raise OSCDecodeError(f"Unexpected end of data at offset {offset} while reading OSC-string")

    null_idx = data.find(b"\x00", offset)
    if null_idx == -1:
        raise OSCDecodeError(f"No null terminator found for OSC-string starting at offset {offset}")

    str_bytes = data[offset:null_idx]
    try:
        s = str_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OSCDecodeError(f"Invalid UTF-8 in OSC-string at offset {offset}: {exc}") from exc

    # End of string boundary (including 4-byte padding)
    next_offset = (null_idx + 4) & ~3
    if next_offset > len(data):
        raise OSCDecodeError(
            f"OSC-string padding exceeds packet boundary: next_offset={next_offset} > len={len(data)}"
        )

    # Validate that all padding bytes are null
    padding = data[null_idx:next_offset]
    if any(b != 0 for b in padding):
        raise OSCDecodeError(f"Corrupt null padding in OSC-string at offset {null_idx}")

    return s, next_offset


def encode_osc_blob(b: bytes) -> bytes:
    """Encodes arbitrary bytes as an OSC-blob (int32 length + 0 to 3 null padding bytes)."""
    length_header = struct.pack(">i", len(b))
    pad_len = (4 - (len(b) % 4)) % 4
    return length_header + b + (b"\x00" * pad_len)


def decode_osc_blob(data: bytes, offset: int = 0) -> Tuple[bytes, int]:
    """Decodes an OSC-blob from data at offset.
    
    Returns (blob_bytes, new_offset).
    Raises OSCDecodeError if blob is malformed or truncated.
    """
    if offset + 4 > len(data):
        raise OSCDecodeError(f"Truncated blob size header at offset {offset}")

    blob_len = struct.unpack(">i", data[offset:offset + 4])[0]
    if blob_len < 0:
        raise OSCDecodeError(f"Negative blob length {blob_len} at offset {offset}")

    offset += 4
    if offset + blob_len > len(data):
        raise OSCDecodeError(
            f"Truncated blob payload: expected {blob_len} bytes, available {len(data) - offset}"
        )

    blob_data = data[offset:offset + blob_len]
    pad_len = (4 - (blob_len % 4)) % 4
    next_offset = offset + blob_len + pad_len
    if next_offset > len(data):
        raise OSCDecodeError(f"Blob padding exceeds packet boundary at offset {next_offset}")

    # Validate that all padding bytes are null
    padding = data[offset + blob_len:next_offset]
    if any(b != 0 for b in padding):
        raise OSCDecodeError(f"Corrupt null padding in OSC-blob at offset {offset + blob_len}")

    return blob_data, next_offset


def encode_osc_message(address: str, *args: Any) -> bytes:
    """Encodes an OSC 1.0 message packet.
    
    Args:
        address: OSC address pattern starting with '/' (e.g. '/input_locker/lock').
        *args: Atomic arguments (int, float, str, bytes, bool, None).
        
    Returns:
        bytes: RFC-compliant 4-byte aligned binary OSC message packet.
    """
    if not address.startswith("/"):
        raise OSCEncodeError(f"OSC address must begin with '/': {address!r}")

    addr_bytes = encode_osc_string(address)

    # Build type tag and serialized arguments
    type_tags = [","]
    payload_parts = []

    for arg in args:
        if isinstance(arg, bool):
            # Booleans use 'T' or 'F' tags with 0 payload bytes
            type_tags.append("T" if arg else "F")
        elif isinstance(arg, int):
            if -2147483648 <= arg <= 2147483647:
                type_tags.append("i")
                payload_parts.append(struct.pack(">i", arg))
            else:
                type_tags.append("h")
                payload_parts.append(struct.pack(">q", arg))
        elif isinstance(arg, float):
            type_tags.append("f")
            payload_parts.append(struct.pack(">f", arg))
        elif isinstance(arg, str):
            type_tags.append("s")
            payload_parts.append(encode_osc_string(arg))
        elif isinstance(arg, (bytes, bytearray)):
            type_tags.append("b")
            payload_parts.append(encode_osc_blob(bytes(arg)))
        elif arg is None:
            type_tags.append("N")
        else:
            # Fallback to string representation for unsupported types
            type_tags.append("s")
            payload_parts.append(encode_osc_string(str(arg)))

    tag_str = "".join(type_tags)
    tag_bytes = encode_osc_string(tag_str)
    return addr_bytes + tag_bytes + b"".join(payload_parts)


def decode_osc_message(data: bytes) -> OSCMessage:
    """Decodes a binary OSC 1.0 message packet.
    
    Args:
        data: Binary OSC datagram.
        
    Returns:
        OSCMessage: Decoded address, arguments, and type tags.
        
    Raises:
        OSCDecodeError: If the datagram is malformed, truncated, or invalid.
    """
    if len(data) < 4:
        raise OSCDecodeError(f"OSC packet too short ({len(data)} bytes, min 4 bytes)")

    if not data.startswith(b"/"):
        raise OSCDecodeError(f"OSC address pattern must start with '/': {data[:8]!r}")

    address, offset = decode_osc_string(data, 0)

    # Check if there is a type tag string
    if offset >= len(data):
        # No type tags: valid OSC message with 0 arguments
        return OSCMessage(address=address, args=(), type_tags="")

    # Decode type tag string
    if data[offset:offset + 1] != b",":
        raise OSCDecodeError(f"Expected comma ',' at start of type tag string, got {data[offset:offset + 1]!r}")

    type_tag_str, offset = decode_osc_string(data, offset)

    # Parse arguments
    args: List[Any] = []
    # type_tag_str starts with ','
    tags = type_tag_str[1:]

    for tag in tags:
        if tag == "i":
            if offset + 4 > len(data):
                raise OSCDecodeError(f"Truncated int32 argument at offset {offset}")
            val = struct.unpack(">i", data[offset:offset + 4])[0]
            args.append(val)
            offset += 4
        elif tag == "f":
            if offset + 4 > len(data):
                raise OSCDecodeError(f"Truncated float32 argument at offset {offset}")
            val = struct.unpack(">f", data[offset:offset + 4])[0]
            args.append(round(val, 6))
            offset += 4
        elif tag == "s":
            s_val, offset = decode_osc_string(data, offset)
            args.append(s_val)
        elif tag == "b":
            b_val, offset = decode_osc_blob(data, offset)
            args.append(b_val)
        elif tag == "h":
            if offset + 8 > len(data):
                raise OSCDecodeError(f"Truncated int64 argument at offset {offset}")
            val = struct.unpack(">q", data[offset:offset + 8])[0]
            args.append(val)
            offset += 8
        elif tag == "d":
            if offset + 8 > len(data):
                raise OSCDecodeError(f"Truncated float64 argument at offset {offset}")
            val = struct.unpack(">d", data[offset:offset + 8])[0]
            args.append(val)
            offset += 8
        elif tag == "T":
            args.append(True)
        elif tag == "F":
            args.append(False)
        elif tag == "N":
            args.append(None)
        else:
            raise OSCDecodeError(f"Unsupported OSC type tag '{tag}' at offset {offset}")

    return OSCMessage(address=address, args=tuple(args), type_tags=type_tag_str)


def encode_osc_bundle(timetag: int = 1, *elements: Union[bytes, OSCMessage, OSCBundle]) -> bytes:
    """Encodes an OSC 1.0 bundle packet.
    
    Structure:
    - 8-byte header: '#bundle\\x00'
    - 8-byte NTP timetag (>Q)
    - Sequence of bundle elements, each prefixed by an int32 length header (>i)
    """
    bundle_header = b"#bundle\x00"
    timetag_bytes = struct.pack(">Q", timetag)
    body = bytearray()
    for elem in elements:
        if isinstance(elem, bytes):
            elem_bytes = elem
        elif isinstance(elem, OSCMessage):
            elem_bytes = encode_osc_message(elem.address, *elem.args)
        elif isinstance(elem, OSCBundle):
            elem_bytes = encode_osc_bundle(elem.timetag, *elem.elements)
        else:
            raise OSCEncodeError(f"Unsupported bundle element type: {type(elem).__name__}")
        body.extend(struct.pack(">i", len(elem_bytes)))
        body.extend(elem_bytes)
    return bundle_header + timetag_bytes + bytes(body)


def decode_osc_bundle(data: bytes) -> OSCBundle:
    """Decodes a binary OSC 1.0 bundle packet.
    
    Raises OSCDecodeError if the bundle is corrupt, truncated, or invalid.
    """
    if len(data) < 16:
        raise OSCDecodeError(f"OSC bundle too short ({len(data)} bytes, minimum 16 bytes)")
    if not data.startswith(b"#bundle\x00"):
        raise OSCDecodeError(f"OSC bundle must start with '#bundle\\x00', got {data[:8]!r}")

    timetag = struct.unpack(">Q", data[8:16])[0]
    offset = 16
    elements: List[Union[OSCMessage, OSCBundle]] = []

    while offset < len(data):
        if offset + 4 > len(data):
            raise OSCDecodeError(f"Truncated bundle element size header at offset {offset}")
        elem_len = struct.unpack(">i", data[offset:offset + 4])[0]
        offset += 4
        if elem_len < 0 or offset + elem_len > len(data):
            raise OSCDecodeError(f"Invalid bundle element length {elem_len} at offset {offset}")

        elem_bytes = data[offset:offset + elem_len]
        offset += elem_len

        if elem_bytes.startswith(b"#bundle\x00"):
            elements.append(decode_osc_bundle(elem_bytes))
        elif elem_bytes.startswith(b"/"):
            elements.append(decode_osc_message(elem_bytes))
        else:
            raise OSCDecodeError(f"Unrecognized bundle element content: {elem_bytes[:8]!r}")

    return OSCBundle(timetag=timetag, elements=tuple(elements))


def decode_osc_packet(data: bytes) -> Union[OSCMessage, OSCBundle]:
    """Decodes any OSC packet (either an OSCMessage or OSCBundle)."""
    if data.startswith(b"#bundle\x00"):
        return decode_osc_bundle(data)
    elif data.startswith(b"/"):
        return decode_osc_message(data)
    raise OSCDecodeError(f"Unrecognized OSC packet header: {data[:8]!r}")


def try_decode_osc_message(data: bytes) -> Optional[OSCMessage]:
    """Attempts to decode an OSC message, returning None on error without raising."""
    try:
        return decode_osc_message(data)
    except (OSCDecodeError, Exception):
        return None


class OSCHandler:
    """Handles and dispatches OSC 1.0 messages to the Input Locker controller."""

    # Standard OSC Addresses
    ADDR_LOCK = "/input_locker/lock"
    ADDR_UNLOCK = "/input_locker/unlock"
    ADDR_STATUS = "/input_locker/status"
    ADDR_TOGGLE = "/input_locker/toggle"

    def __init__(self, controller: Any, start_time: Optional[float] = None):
        """Initializes the OSC Handler.
        
        Args:
            controller: State machine or coordinator implementing lock(), unlock(), etc.
            start_time: Monotonic process start time for uptime calculation.
        """
        self.controller = controller
        self.start_time = start_time if start_time is not None else time.monotonic()

    @property
    def uptime(self) -> float:
        """Returns uptime in seconds."""
        return round(time.monotonic() - self.start_time, 3)

    def _get_state_str(self) -> str:
        """Retrieves the current controller state as a string."""
        if hasattr(self.controller, "state"):
            st = self.controller.state
            if hasattr(st, "value"):
                return str(st.value).upper()
            return str(st).upper()
        if hasattr(self.controller, "is_locked"):
            locked = self.controller.is_locked
            if callable(locked):
                locked = locked()
            return "LOCKED" if locked else "UNLOCKED"
        return "UNKNOWN"

    def _is_swallowing(self) -> bool:
        """Retrieves whether input swallowing is currently active."""
        if hasattr(self.controller, "hook_mgr") and hasattr(self.controller.hook_mgr, "is_swallowing"):
            return bool(self.controller.hook_mgr.is_swallowing())
        if hasattr(self.controller, "swallow_active"):
            return bool(self.controller.swallow_active)
        return self._get_state_str() == "LOCKED"

    def handle_packet(self, data: bytes, addr: Optional[Tuple[str, int]] = None) -> Optional[bytes]:
        """Parses an incoming OSC datagram, executes the command, and returns the response datagram.
        
        Args:
            data: Raw binary UDP datagram.
            addr: Sender's (host, port) tuple.
            
        Returns:
            bytes: OSC reply datagram to send back to sender, or None if unhandled.
        """
        if data.startswith(b"#bundle\x00"):
            try:
                bundle = decode_osc_bundle(data)
                replies = []
                for elem in bundle.elements:
                    if isinstance(elem, OSCMessage):
                        rep = self.handle_message(elem)
                        if rep is not None:
                            replies.append(rep)
                if len(replies) == 1:
                    return replies[0]
                elif len(replies) > 1:
                    return encode_osc_bundle(1, *replies)
                return None
            except Exception:
                return None

        msg = try_decode_osc_message(data)
        if msg is None:
            return None

        return self.handle_message(msg)

    def handle_message(self, msg: OSCMessage) -> Optional[bytes]:
        """Executes a decoded OSC message and returns the reply datagram."""
        # Normalize address pattern (strip trailing slashes, lower case for matching)
        norm_address = msg.address.rstrip("/").lower()

        if norm_address == self.ADDR_LOCK.lower():
            # Trigger Lock
            latency_ms = 0.0
            if hasattr(self.controller, "request_lock"):
                res = self.controller.request_lock(source="osc")
                if isinstance(res, dict):
                    latency_ms = float(res.get("latency_ms") or res.get("stats", {}).get("total_ms") or 0.0)
            elif hasattr(self.controller, "lock"):
                res = self.controller.lock()
                if isinstance(res, dict):
                    latency_ms = float(res.get("latency_ms") or res.get("stats", {}).get("total_ms") or 0.0)

            state = self._get_state_str()
            # Reply with /input_locker/lock (or reply pattern)
            return encode_osc_message("/input_locker/lock", state, float(round(latency_ms, 3)))

        elif norm_address == self.ADDR_UNLOCK.lower():
            # Trigger Unlock
            latency_ms = 0.0
            if hasattr(self.controller, "request_unlock"):
                res = self.controller.request_unlock(source="osc")
                if isinstance(res, dict):
                    latency_ms = float(res.get("latency_ms") or res.get("stats", {}).get("total_ms") or 0.0)
            elif hasattr(self.controller, "unlock"):
                res = self.controller.unlock()
                if isinstance(res, dict):
                    latency_ms = float(res.get("latency_ms") or res.get("stats", {}).get("total_ms") or 0.0)

            state = self._get_state_str()
            return encode_osc_message("/input_locker/unlock", state, float(round(latency_ms, 3)))

        elif norm_address == self.ADDR_STATUS.lower():
            # Query Status: replies with /input_locker/status (state, uptime, swallowing)
            state = self._get_state_str()
            uptime_s = self.uptime
            swallow_int = 1 if self._is_swallowing() else 0
            return encode_osc_message(self.ADDR_STATUS, state, uptime_s, swallow_int)

        elif norm_address == self.ADDR_TOGGLE.lower():
            # Toggle state
            current = self._get_state_str()
            if current == "LOCKED":
                if hasattr(self.controller, "request_unlock"):
                    self.controller.request_unlock(source="osc_toggle")
                elif hasattr(self.controller, "unlock"):
                    self.controller.unlock()
            else:
                if hasattr(self.controller, "request_lock"):
                    self.controller.request_lock(source="osc_toggle")
                elif hasattr(self.controller, "lock"):
                    self.controller.lock()

            new_state = self._get_state_str()
            return encode_osc_message("/input_locker/toggle", new_state, self.uptime)

        else:
            # Unknown address
            return encode_osc_message("/input_locker/error", f"Unknown OSC address: {msg.address}")
