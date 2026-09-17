"""Unit tests for SingleInstanceManager and single-instance process enforcement."""
from __future__ import annotations

import threading
import time
import uuid

import pytest

from input_locker.core.single_instance import (
    SingleInstanceManager,
    focus_existing_window,
)


def _unique_names():
    uid = uuid.uuid4().hex[:8]
    return f"Local\\Test_InputLocker_Mutex_{uid}", f"Local\\Test_InputLocker_Event_{uid}"


class TestSingleInstanceManager:
    """Test suite for single-instance enforcement and IPC."""

    def test_acquire_first_instance_succeeds(self):
        m_name, e_name = _unique_names()
        mgr = SingleInstanceManager(mutex_name=m_name, event_name=e_name)
        try:
            assert mgr.acquire() is True
        finally:
            mgr.release()

    def test_acquire_duplicate_instance_fails(self):
        m_name, e_name = _unique_names()
        mgr1 = SingleInstanceManager(mutex_name=m_name, event_name=e_name)
        mgr2 = SingleInstanceManager(mutex_name=m_name, event_name=e_name)
        try:
            assert mgr1.acquire() is True
            assert mgr2.acquire() is False
        finally:
            mgr1.release()
            mgr2.release()

    def test_release_allows_subsequent_acquire(self):
        m_name, e_name = _unique_names()
        mgr1 = SingleInstanceManager(mutex_name=m_name, event_name=e_name)
        mgr2 = SingleInstanceManager(mutex_name=m_name, event_name=e_name)

        assert mgr1.acquire() is True
        assert mgr2.acquire() is False

        # Release first instance
        mgr1.release()

        # Second instance should now successfully acquire
        assert mgr2.acquire() is True
        mgr2.release()

    def test_listener_and_notify_event(self):
        m_name, e_name = _unique_names()
        mgr1 = SingleInstanceManager(mutex_name=m_name, event_name=e_name)
        mgr2 = SingleInstanceManager(mutex_name=m_name, event_name=e_name)

        called = threading.Event()
        shutdown = threading.Event()

        try:
            assert mgr1.acquire() is True
            mgr1.start_listener(on_request_callback=lambda: called.set(), shutdown_event=shutdown)

            # Secondary instance notifies
            mgr2.notify_existing_instance()

            # Wait for event to trigger callback
            assert called.wait(timeout=2.0) is True
        finally:
            shutdown.set()
            mgr1.release()
            mgr2.release()

    def test_focus_existing_window_safe(self):
        # Should execute safely without raising any exceptions
        result = focus_existing_window()
        assert isinstance(result, bool)
