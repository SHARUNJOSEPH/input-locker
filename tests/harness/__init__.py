# tests/harness/__init__.py
"""Test harness package for Windows AV Staging Input Locker.

Exposes:
- CompanionFocusHarness / FocusHarness: Real Win32 focus message logger
- InputInjector: Win32 SendInput wrapper with 40-byte 64-bit alignment
- LockerTCPClient, LockerUDPClient, LockerOSCClient: Show control test clients
"""

from .focus_harness import CompanionFocusHarness, FocusHarness
from .input_injector import InputInjector
from .client_harness import LockerTCPClient, LockerUDPClient, LockerOSCClient

__all__ = [
    "CompanionFocusHarness",
    "FocusHarness",
    "InputInjector",
    "LockerTCPClient",
    "LockerUDPClient",
    "LockerOSCClient",
]
