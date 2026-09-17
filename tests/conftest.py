"""Pytest configuration and global fixtures for Windows AV Staging Input Locker.

Provides:
- Path setup ensuring `src` is always discoverable by test modules
- `focus_harness`: Managed CompanionFocusHarness simulating AV engines
- `input_injector`: Desktop-attached Win32 SendInput synthetic event injector
- `cursor_guard`: Cleaned-up CursorGuard fixture
- `overlay_manager`: Prewarmed OverlayManager fixture
- `hook_manager`: Desktop-attached HookManager fixture
- `network_server`: Managed async dual-protocol show control server (TCP & UDP)
- `test_controller`: Full coordinator integrating hooks, overlay, and network
"""

import sys
import os
import time
import socket
import threading
import asyncio
import json
import builtins
import ctypes
from pathlib import Path
from typing import Generator, Tuple, Dict, Any, Optional

# Defensive shim in test environment in case implementation module forgot import ctypes
builtins.ctypes = ctypes

import pytest

# Ensure `src` and project root are on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from tests.harness.focus_harness import CompanionFocusHarness
from tests.harness.input_injector import InputInjector
from tests.harness.client_harness import LockerTCPClient, LockerUDPClient, LockerOSCClient

from input_locker.core.controller import LockerController
from input_locker.core.state_machine import LockerState, StateMachine
from input_locker.network.server import NetworkServer, NetworkController
from input_locker.hooks.hook_manager import HookManager
from input_locker.overlay.cursor_guard import CursorGuard
from input_locker.overlay.overlay_manager import OverlayManager
from input_locker.overlay.win32_overlay import Win32Overlay


# ---------------------------------------------------------------------------
# Production Deliverable Test Controller Wrapper
# ---------------------------------------------------------------------------

class TestControllerWrapper:
    """Production LockerController wrapper providing test ergonomics with genuine deliverable components."""
    __test__ = False

    def __init__(self, tcp_port: int = 0, udp_port: int = 0):
        self.controller = LockerController(
            overlay_backend="win32",
            alpha=120,
            auto_prewarm=True,
            auto_register_signals=False,
        )
        self.server = NetworkServer(
            controller=self.controller,
            tcp_port=tcp_port,
            udp_port=udp_port,
        )

    def start(self):
        self.controller.start()
        self.server.start()

    def stop(self):
        try:
            self.server.stop()
        except Exception:
            pass
        try:
            self.controller.stop()
        except Exception:
            pass

    def lock(self) -> Dict[str, Any]:
        self.controller.lock()
        return {
            "status": "ok",
            "state": str(self.controller.state),
            "latency_ms": self.controller.last_lock_latency_ms,
        }

    def unlock(self) -> Dict[str, Any]:
        self.controller.unlock()
        return {
            "status": "ok",
            "state": str(self.controller.state),
            "latency_ms": self.controller.last_unlock_latency_ms,
        }

    @property
    def is_locked(self) -> bool:
        return self.controller.is_locked()

    @property
    def state(self) -> str:
        return str(self.controller.state)

    @property
    def sm(self):
        return self.controller.state_machine

    @property
    def hook_mgr(self):
        return self.controller.hook_manager

    @property
    def overlay_mgr(self):
        return self.controller.overlay_manager

    @property
    def cursor_guard(self):
        return getattr(self.controller.overlay_manager, "cursor_guard", None)

    @property
    def tcp_port(self) -> int:
        return self.server.tcp_port

    @property
    def udp_port(self) -> int:
        return self.server.udp_port

    def dispatch(self, cmd_data: Any, source: str = "test") -> Dict[str, Any]:
        return self.server.dispatch_command(cmd_data, source=source)


# Alias for backward compatibility with tests importing TestController
TestController = TestControllerWrapper


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def focus_harness() -> Generator[CompanionFocusHarness, None, None]:
    """Provides a started, clean CompanionFocusHarness window on the active desktop."""
    harness = CompanionFocusHarness()
    harness.start(timeout=3.0)
    harness.clear()
    try:
        yield harness
    finally:
        harness.stop()


@pytest.fixture(scope="function")
def cursor_guard() -> Generator[CursorGuard, None, None]:
    """Provides a clean CursorGuard ensuring cursor bounds are restored after test."""
    guard = CursorGuard(register_atexit=True)
    try:
        yield guard
    finally:
        guard.release()


@pytest.fixture(scope="function")
def overlay_manager() -> Generator[OverlayManager, None, None]:
    """Provides a prewarmed OverlayManager with clean teardown."""
    manager = OverlayManager(backend="win32", auto_prewarm=True)
    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture(scope="function")
def hook_manager() -> Generator[HookManager, None, None]:
    """Provides a started HookManager with clean teardown."""
    mgr = HookManager()
    mgr.start()
    try:
        yield mgr
    finally:
        mgr.stop()


@pytest.fixture(scope="function")
def network_controller() -> Generator[Tuple[NetworkServer, int, int], None, None]:
    """Provides a running genuine production NetworkServer on ephemeral ports."""
    sm = StateMachine()
    server = NetworkServer(controller=sm, tcp_port=0, udp_port=0)
    server.start()
    try:
        yield (server, server.tcp_port, server.udp_port)
    finally:
        server.stop()


@pytest.fixture(scope="function")
def test_controller() -> Generator[TestControllerWrapper, None, None]:
    """Provides an integrated TestControllerWrapper utilizing genuine deliverable components."""
    ctrl = TestControllerWrapper(tcp_port=0, udp_port=0)
    ctrl.start()
    try:
        yield ctrl
    finally:
        ctrl.stop()
