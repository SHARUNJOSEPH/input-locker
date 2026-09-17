"""Thread-safe Finite State Machine for Windows AV Staging Input Locker.

Coordinates the 4-state lifecycle (UNLOCKED, LOCKING, LOCKED, UNLOCKING),
enforces transition invariants, guarantees idempotence, tracks microsecond-level
transition latency, and dispatches state change callbacks to subscribers.
"""

from __future__ import annotations

from enum import Enum
import logging
import threading
import time
from typing import Callable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class LockerState(str, Enum):
    """4-state model for the Input Locker FSM."""
    UNLOCKED = "UNLOCKED"
    LOCKING = "LOCKING"
    LOCKED = "LOCKED"
    UNLOCKING = "UNLOCKING"

    def __str__(self) -> str:
        return self.value


class StateMachineError(Exception):
    """Base exception for state machine errors."""
    pass


class InvalidStateTransitionError(StateMachineError):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, current_state: LockerState, target_state: LockerState) -> None:
        self.current_state = current_state
        self.target_state = target_state
        super().__init__(
            f"Invalid transition from {current_state.value} to {target_state.value}"
        )


# Valid state transitions mapping
VALID_TRANSITIONS: dict[LockerState, Set[LockerState]] = {
    LockerState.UNLOCKED: {LockerState.LOCKING},
    LockerState.LOCKING: {LockerState.LOCKED, LockerState.UNLOCKED},
    LockerState.LOCKED: {LockerState.UNLOCKING},
    LockerState.UNLOCKING: {LockerState.UNLOCKED, LockerState.LOCKED},
}


class StateMachine:
    """Thread-safe 4-state Finite State Machine.
    
    Attributes:
        state: Current LockerState.
        last_transition_latency_ms: Latency of the most recent transition in milliseconds.
    """

    def __init__(
        self,
        initial_state: LockerState = LockerState.UNLOCKED,
        on_state_change: Optional[Callable[[LockerState, LockerState], None]] = None,
    ) -> None:
        """Initialize the State Machine.
        
        Args:
            initial_state: Starting state (defaults to UNLOCKED).
            on_state_change: Optional initial callback for state changes.
        """
        self._lock = threading.RLock()
        self._state: LockerState = initial_state
        self._listeners: List[Callable[[LockerState, LockerState], None]] = []

        if on_state_change is not None:
            self._listeners.append(on_state_change)

        # Transition telemetry
        self._last_transition_start: float = time.perf_counter()
        self._last_transition_end: float = self._last_transition_start
        self._last_transition_latency_ms: float = 0.0
        self._total_transitions: int = 0
        self._history: List[Tuple[float, LockerState, LockerState, float]] = []

    @property
    def state(self) -> LockerState:
        """Return the current state atomically."""
        with self._lock:
            return self._state

    def is_locked(self) -> bool:
        """Return True if currently in LOCKED state."""
        with self._lock:
            return self._state == LockerState.LOCKED

    def is_unlocked(self) -> bool:
        """Return True if currently in UNLOCKED state."""
        with self._lock:
            return self._state == LockerState.UNLOCKED

    def is_locking(self) -> bool:
        """Return True if currently in LOCKING transition."""
        with self._lock:
            return self._state == LockerState.LOCKING

    def is_unlocking(self) -> bool:
        """Return True if currently in UNLOCKING transition."""
        with self._lock:
            return self._state == LockerState.UNLOCKING

    def is_swallowing(self) -> bool:
        """Return True if input swallowing should be active (LOCKING or LOCKED)."""
        with self._lock:
            return self._state in (LockerState.LOCKING, LockerState.LOCKED)

    @property
    def last_transition_latency_ms(self) -> float:
        """Return latency of the last state transition in milliseconds."""
        with self._lock:
            return self._last_transition_latency_ms

    @property
    def total_transitions(self) -> int:
        """Return total number of executed state transitions."""
        with self._lock:
            return self._total_transitions

    @property
    def history(self) -> List[Tuple[float, LockerState, LockerState, float]]:
        """Return copy of transition history [(timestamp, from_state, to_state, latency_ms)]."""
        with self._lock:
            return list(self._history)

    def add_listener(self, listener: Callable[[LockerState, LockerState], None]) -> None:
        """Register a callback to receive (old_state, new_state) notifications."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[LockerState, LockerState], None]) -> None:
        """Unregister a previously registered callback."""
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def transition_to(self, target_state: LockerState) -> bool:
        """Perform a validated state transition.
        
        Args:
            target_state: The desired destination LockerState.
            
        Returns:
            bool: True if transition succeeded or was an idempotent no-op.
            
        Raises:
            InvalidStateTransitionError: If the transition violates FSM invariants.
        """
        start_time = time.perf_counter()
        callbacks_to_invoke: List[Callable[[LockerState, LockerState], None]] = []

        with self._lock:
            old_state = self._state

            # Idempotency check: transitioning to current state is a safe no-op
            if old_state == target_state:
                logger.debug("State transition no-op: already in %s", target_state.value)
                return True

            # Invariant check: validate transition path
            allowed = VALID_TRANSITIONS.get(old_state, set())
            if target_state not in allowed:
                logger.warning(
                    "Illegal transition requested: %s -> %s",
                    old_state.value,
                    target_state.value,
                )
                raise InvalidStateTransitionError(old_state, target_state)

            # Apply state transition
            self._state = target_state
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000.0

            self._last_transition_start = start_time
            self._last_transition_end = end_time
            self._last_transition_latency_ms = latency_ms
            self._total_transitions += 1

            # Keep bounded history (last 1000 transitions)
            self._history.append((end_time, old_state, target_state, latency_ms))
            if len(self._history) > 1000:
                self._history.pop(0)

            callbacks_to_invoke = list(self._listeners)

            logger.info(
                "State changed: %s -> %s (%.3f ms)",
                old_state.value,
                target_state.value,
                latency_ms,
            )

        # Dispatch callbacks outside lock to prevent deadlocks with subscribers
        for callback in callbacks_to_invoke:
            try:
                callback(old_state, target_state)
            except Exception as exc:
                logger.error("Error in state change callback: %s", exc, exc_info=True)

        return True

    def lock(self) -> bool:
        """High-level lock transition: moves UNLOCKED -> LOCKING -> LOCKED.
        
        Idempotent: returns True without error if already LOCKED or LOCKING.
        """
        with self._lock:
            if self._state in (LockerState.LOCKED, LockerState.LOCKING):
                return True
            self.transition_to(LockerState.LOCKING)
            self.transition_to(LockerState.LOCKED)
            return True

    def unlock(self) -> bool:
        """High-level unlock transition: moves LOCKED -> UNLOCKING -> UNLOCKED.
        
        Idempotent: returns True without error if already UNLOCKED or UNLOCKING.
        """
        with self._lock:
            if self._state in (LockerState.UNLOCKED, LockerState.UNLOCKING):
                return True
            self.transition_to(LockerState.UNLOCKING)
            self.transition_to(LockerState.UNLOCKED)
            return True

    def reset(self) -> None:
        """Reset state machine unconditionally to UNLOCKED."""
        with self._lock:
            self._state = LockerState.UNLOCKED
