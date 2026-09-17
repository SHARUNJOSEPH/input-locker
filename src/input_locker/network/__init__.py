"""Network Remote Control Subsystem for Windows AV Staging Input Locker.

Provides asynchronous dual-protocol remote show control over:
- OSC 1.0 (UDP port 9000 by default) for live AV software (QLab, Bitfocus Companion, Resolume)
- Line-delimited JSON (TCP port 9001 by default) for automated testing, monitoring, and telemetry
"""

from __future__ import annotations

from input_locker.network.osc_handler import (
    OSCBundle,
    OSCDecodeError,
    OSCEncodeError,
    OSCError,
    OSCHandler,
    OSCMessage,
    decode_osc_bundle,
    decode_osc_message,
    decode_osc_packet,
    encode_osc_bundle,
    encode_osc_message,
    try_decode_osc_message,
)
from input_locker.network.server import NetworkController, NetworkServer
from input_locker.network.tcp_handler import TCPCommandError, TCPHandler

__all__ = [
    "NetworkServer",
    "NetworkController",
    "OSCHandler",
    "OSCMessage",
    "OSCBundle",
    "OSCError",
    "OSCDecodeError",
    "OSCEncodeError",
    "encode_osc_message",
    "encode_osc_bundle",
    "decode_osc_message",
    "decode_osc_bundle",
    "decode_osc_packet",
    "try_decode_osc_message",
    "TCPHandler",
    "TCPCommandError",
]
