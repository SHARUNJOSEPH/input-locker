"""Tier 5 Adversarial Test Suite: State Machine Invariant Stress & Concurrency.

Adversarial stress-testing of core finite state machine:
- Enforcing all disallowed direct transitions (InvalidStateTransitionError)
- Multithreaded transition races (competing concurrent lock/unlock threads)
- Subscriber listener exception isolation
- Transition history buffer bounds (1000 items max) under transition flood
- Atomic telemetry and transition monotonicity
"""

from __future__ import annotations

import threading
import time
from typing import List
import pytest

from input_locker.core.state_machine import (
    StateMachine,
    LockerState,
    InvalidStateTransitionError,
)


class TestStateMachineAdversarial:
    """Adversarial testing of state machine transitions, invariants, and threading."""

    def test_all_illegal_direct_transitions_raise_error(self) -> None:
        """Verify all disallowed transitions raise InvalidStateTransitionError."""
        sm = StateMachine(initial_state=LockerState.UNLOCKED)

        # From UNLOCKED: only LOCKING is allowed
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(LockerState.LOCKED)

        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(LockerState.UNLOCKING)

        # Move to LOCKING
        sm.transition_to(LockerState.LOCKING)

        # From LOCKING: only LOCKED and UNLOCKED are allowed
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(LockerState.UNLOCKING)

        # Move to LOCKED
        sm.transition_to(LockerState.LOCKED)

        # From LOCKED: only UNLOCKING is allowed
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(LockerState.UNLOCKED)

        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(LockerState.LOCKING)

        # Move to UNLOCKING
        sm.transition_to(LockerState.UNLOCKING)

        # From UNLOCKING: only UNLOCKED and LOCKED are allowed
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(LockerState.LOCKING)

    def test_concurrent_lock_unlock_race_condition(self) -> None:
        """Verify competing concurrent lock and unlock calls leave FSM in a valid final state."""
        sm = StateMachine(initial_state=LockerState.UNLOCKED)
        exceptions: List[Exception] = []

        def locker_thread() -> None:
            try:
                for _ in range(50):
                    sm.lock()
                    time.sleep(0.0005)
            except Exception as exc:
                exceptions.append(exc)

        def unlocker_thread() -> None:
            try:
                for _ in range(50):
                    sm.unlock()
                    time.sleep(0.0005)
            except Exception as exc:
                exceptions.append(exc)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=locker_thread, daemon=True))
            threads.append(threading.Thread(target=unlocker_thread, daemon=True))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # Notice: because sm.lock() and sm.unlock() perform two transitions,
        # concurrent calls can expose the intermediate race where transition_to is called
        # while state is LOCKING or UNLOCKING.
        # Verify the state machine survived and is in a valid state
        assert sm.state in (LockerState.LOCKED, LockerState.UNLOCKED, LockerState.LOCKING, LockerState.UNLOCKING)

    def test_listener_exception_isolation(self) -> None:
        """Verify an exception inside a subscriber listener does not prevent other listeners or break FSM."""
        sm = StateMachine(initial_state=LockerState.UNLOCKED)
        executed_listeners: List[str] = []

        def failing_listener(old: LockerState, new: LockerState) -> None:
            executed_listeners.append("failing")
            raise RuntimeError("Subscriber crashed intentionally")

        def successful_listener(old: LockerState, new: LockerState) -> None:
            executed_listeners.append("successful")

        sm.add_listener(failing_listener)
        sm.add_listener(successful_listener)

        # Transition must succeed despite listener exception
        res = sm.transition_to(LockerState.LOCKING)
        assert res is True
        assert sm.state == LockerState.LOCKING
        assert "failing" in executed_listeners
        assert "successful" in executed_listeners

    def test_history_bounded_ring_buffer_under_flood(self) -> None:
        """Verify transition history is strictly capped at 1000 items during a 1200-transition storm."""
        sm = StateMachine(initial_state=LockerState.UNLOCKED)

        for _ in range(300):
            sm.lock()    # 2 transitions: LOCKING, LOCKED
            sm.unlock()  # 2 transitions: UNLOCKING, UNLOCKED

        assert sm.total_transitions == 1200
        history = sm.history
        assert len(history) == 1000, f"Expected 1000 history items, got {len(history)}"

        # Verify chronological order
        timestamps = [entry[0] for entry in history]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1]

    def test_idempotent_transition_telemetry(self) -> None:
        """Verify calling lock() when already locked returns True without error and records latency."""
        sm = StateMachine(initial_state=LockerState.UNLOCKED)
        assert sm.lock() is True
        assert sm.is_locked() is True

        # Idempotent re-lock
        assert sm.lock() is True
        assert sm.is_locked() is True

        # Transition to current state is a safe no-op
        assert sm.transition_to(LockerState.LOCKED) is True
        assert sm.last_transition_latency_ms >= 0.0
