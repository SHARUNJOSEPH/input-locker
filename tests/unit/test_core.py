"""Unit tests for input_locker.core (State Machine, Controller, and Keyup Bugfix).

Tests FSM transition invariants, latency (<200ms budget), idempotence,
thread safety under contention, controller lifecycle sequencing, and the
keyup leak prevention bugfix.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import List, Tuple
from unittest.mock import MagicMock, call, patch

import pytest

from input_locker.core.state_machine import (
    InvalidStateTransitionError,
    LockerState,
    StateMachine,
    VALID_TRANSITIONS,
)
from input_locker.core.controller import LockerController
from input_locker.hooks.event_filter import (
    ALT_KEYS,
    CTRL_KEYS,
    EventFilter,
    SHIFT_KEYS,
    VK_CONTROL,
    VK_F11,
    VK_LCONTROL,
    VK_LMENU,
    VK_LSHIFT,
    VK_MENU,
    VK_SHIFT,
    VK_U,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
)
from input_locker.main import parse_args, setup_logging


class MockEventData:
    """Mock struct representing KBDLLHOOKSTRUCT."""

    def __init__(self, vkCode: int) -> None:
        self.vkCode = vkCode


# ============================================================================
# 1. State Machine Unit Tests
# ============================================================================

class TestStateMachineTransitions:
    """Tests for StateMachine state transitions and invariants."""

    def test_initial_state_defaults_to_unlocked(self) -> None:
        sm = StateMachine()
        assert sm.state == LockerState.UNLOCKED
        assert sm.is_unlocked() is True
        assert sm.is_locked() is False
        assert sm.is_locking() is False
        assert sm.is_unlocking() is False
        assert sm.is_swallowing() is False

    def test_custom_initial_state(self) -> None:
        sm = StateMachine(initial_state=LockerState.LOCKED)
        assert sm.state == LockerState.LOCKED
        assert sm.is_locked() is True
        assert sm.is_swallowing() is True

    def test_valid_forward_transitions(self) -> None:
        sm = StateMachine()
        # UNLOCKED -> LOCKING
        assert sm.transition_to(LockerState.LOCKING) is True
        assert sm.state == LockerState.LOCKING
        assert sm.is_locking() is True
        assert sm.is_swallowing() is True

        # LOCKING -> LOCKED
        assert sm.transition_to(LockerState.LOCKED) is True
        assert sm.state == LockerState.LOCKED
        assert sm.is_locked() is True
        assert sm.is_swallowing() is True

        # LOCKED -> UNLOCKING
        assert sm.transition_to(LockerState.UNLOCKING) is True
        assert sm.state == LockerState.UNLOCKING
        assert sm.is_unlocking() is True
        assert sm.is_swallowing() is False

        # UNLOCKING -> UNLOCKED
        assert sm.transition_to(LockerState.UNLOCKED) is True
        assert sm.state == LockerState.UNLOCKED
        assert sm.is_unlocked() is True
        assert sm.is_swallowing() is False

    def test_rollback_transitions(self) -> None:
        # LOCKING -> UNLOCKED (abort lock)
        sm = StateMachine()
        sm.transition_to(LockerState.LOCKING)
        assert sm.transition_to(LockerState.UNLOCKED) is True
        assert sm.state == LockerState.UNLOCKED

        # UNLOCKING -> LOCKED (abort unlock)
        sm2 = StateMachine(initial_state=LockerState.LOCKED)
        sm2.transition_to(LockerState.UNLOCKING)
        assert sm2.transition_to(LockerState.LOCKED) is True
        assert sm2.state == LockerState.LOCKED

    def test_invalid_transitions_raise_error(self) -> None:
        sm = StateMachine(initial_state=LockerState.UNLOCKED)

        # UNLOCKED cannot go directly to LOCKED or UNLOCKING
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(LockerState.LOCKED)

        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(LockerState.UNLOCKING)

        # Move to LOCKED
        sm.transition_to(LockerState.LOCKING)
        sm.transition_to(LockerState.LOCKED)

        # LOCKED cannot go directly to UNLOCKED or LOCKING
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(LockerState.UNLOCKED)

        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(LockerState.LOCKING)

    def test_idempotent_transitions_return_true(self) -> None:
        sm = StateMachine(initial_state=LockerState.UNLOCKED)
        # Transitioning to current state is a safe no-op
        assert sm.transition_to(LockerState.UNLOCKED) is True
        assert sm.total_transitions == 0

        sm.transition_to(LockerState.LOCKING)
        assert sm.transition_to(LockerState.LOCKING) is True
        assert sm.total_transitions == 1

    def test_high_level_lock_and_unlock_helpers(self) -> None:
        sm = StateMachine()
        assert sm.lock() is True
        assert sm.state == LockerState.LOCKED

        # Idempotent lock
        assert sm.lock() is True
        assert sm.state == LockerState.LOCKED

        assert sm.unlock() is True
        assert sm.state == LockerState.UNLOCKED

        # Idempotent unlock
        assert sm.unlock() is True
        assert sm.state == LockerState.UNLOCKED

    def test_state_change_callbacks(self) -> None:
        recorded: List[Tuple[LockerState, LockerState]] = []

        def callback(old_s: LockerState, new_s: LockerState) -> None:
            recorded.append((old_s, new_s))

        sm = StateMachine(on_state_change=callback)
        sm.transition_to(LockerState.LOCKING)
        sm.transition_to(LockerState.LOCKED)

        assert len(recorded) == 2
        assert recorded[0] == (LockerState.UNLOCKED, LockerState.LOCKING)
        assert recorded[1] == (LockerState.LOCKING, LockerState.LOCKED)

    def test_add_and_remove_listener(self) -> None:
        sm = StateMachine()
        calls = []
        listener = lambda old_s, new_s: calls.append((old_s, new_s))

        sm.add_listener(listener)
        sm.lock()
        assert len(calls) == 2  # UNLOCKED->LOCKING, LOCKING->LOCKED

        sm.remove_listener(listener)
        sm.unlock()
        assert len(calls) == 2  # Listener was removed, no new calls

    def test_callback_exception_does_not_break_transition(self) -> None:
        def bad_callback(old_s: LockerState, new_s: LockerState) -> None:
            raise RuntimeError("Subscriber crash")

        sm = StateMachine(on_state_change=bad_callback)
        # Transition should still succeed
        assert sm.lock() is True
        assert sm.state == LockerState.LOCKED

    def test_transition_latency_telemetry(self) -> None:
        sm = StateMachine()
        sm.lock()

        assert sm.total_transitions == 2
        assert sm.last_transition_latency_ms >= 0.0
        assert sm.last_transition_latency_ms < 200.0  # Well within 200ms budget
        assert len(sm.history) == 2

    def test_reset_method(self) -> None:
        sm = StateMachine(initial_state=LockerState.LOCKED)
        sm.reset()
        assert sm.state == LockerState.UNLOCKED


class TestStateMachineConcurrency:
    """Thread-safety and concurrency tests for StateMachine."""

    def test_multi_threaded_contention_maintains_invariants(self) -> None:
        sm = StateMachine()
        errors: List[Exception] = []
        stop_event = threading.Event()

        def worker_lock_unlock(worker_id: int) -> None:
            try:
                for _ in range(50):
                    if stop_event.is_set():
                        break
                    sm.lock()
                    assert sm.state in (LockerState.LOCKED, LockerState.LOCKING)
                    time.sleep(0.001)
                    sm.unlock()
                    assert sm.state in (LockerState.UNLOCKED, LockerState.UNLOCKING)
            except Exception as exc:
                errors.append(exc)

        def worker_state_reader() -> None:
            try:
                while not stop_event.is_set():
                    st = sm.state
                    assert st in (
                        LockerState.UNLOCKED,
                        LockerState.LOCKING,
                        LockerState.LOCKED,
                        LockerState.UNLOCKING,
                    )
                    _ = sm.is_locked()
                    _ = sm.is_swallowing()
                    _ = sm.last_transition_latency_ms
                    time.sleep(0.0005)
            except Exception as exc:
                errors.append(exc)

        threads = []
        for i in range(5):
            t = threading.Thread(target=worker_lock_unlock, args=(i,))
            threads.append(t)
        reader = threading.Thread(target=worker_state_reader)
        threads.append(reader)

        for t in threads:
            t.start()

        # Wait for workers to finish
        for t in threads[:5]:
            t.join(timeout=10.0)

        stop_event.set()
        reader.join(timeout=2.0)

        assert len(errors) == 0, f"Thread contention errors occurred: {errors}"


# ============================================================================
# 2. LockerController Lifecycle & Sequencing Tests
# ============================================================================

class TestLockerControllerLifecycle:
    """Tests for LockerController integration and sequence ordering."""

    def test_controller_initialization_defaults(self) -> None:
        controller = LockerController(auto_prewarm=False, auto_register_signals=False)
        assert controller.state == LockerState.UNLOCKED
        assert controller.is_locked() is False
        assert controller.is_swallowing() is False
        controller.stop()

    def test_lock_sequence_execution_order(self) -> None:
        """Verifies the exact 5-step lock sequence:
        1. State -> LOCKING
        2. hook_manager.set_swallow(True)
        3. overlay_manager.confine_cursor()
        4. overlay_manager.show_overlay()
        5. State -> LOCKED
        """
        mock_hook = MagicMock()
        mock_overlay = MagicMock()
        sm = StateMachine()

        call_order = []

        def track_state(old_s: LockerState, new_s: LockerState) -> None:
            call_order.append(f"state:{new_s.value}")

        sm.add_listener(track_state)

        def mock_set_swallow(active: bool) -> None:
            call_order.append(f"swallow:{active}")

        def mock_confine() -> bool:
            call_order.append("confine_cursor")
            return True

        def mock_show() -> bool:
            call_order.append("show_overlay")
            return True

        mock_hook.set_swallow.side_effect = mock_set_swallow
        mock_overlay.confine_cursor.side_effect = mock_confine
        mock_overlay.show_overlay.side_effect = mock_show

        controller = LockerController(
            hook_manager=mock_hook,
            overlay_manager=mock_overlay,
            state_machine=sm,
            auto_prewarm=False,
            auto_register_signals=False,
        )

        res = controller.lock()
        assert res is True
        assert controller.is_locked() is True

        expected_order = [
            "state:LOCKING",
            "swallow:True",
            "confine_cursor",
            "show_overlay",
            "state:LOCKED",
        ]
        assert call_order == expected_order

    def test_unlock_sequence_execution_order(self) -> None:
        """Verifies the exact 5-step unlock sequence:
        1. State -> UNLOCKING
        2. overlay_manager.hide_overlay()
        3. overlay_manager.release_cursor()
        4. hook_manager.set_swallow(False)
        5. State -> UNLOCKED
        """
        mock_hook = MagicMock()
        mock_overlay = MagicMock()
        sm = StateMachine(initial_state=LockerState.LOCKED)

        call_order = []

        def track_state(old_s: LockerState, new_s: LockerState) -> None:
            call_order.append(f"state:{new_s.value}")

        sm.add_listener(track_state)

        def mock_hide() -> bool:
            call_order.append("hide_overlay")
            return True

        def mock_release() -> bool:
            call_order.append("release_cursor")
            return True

        def mock_set_swallow(active: bool) -> None:
            call_order.append(f"swallow:{active}")

        mock_overlay.hide_overlay.side_effect = mock_hide
        mock_overlay.release_cursor.side_effect = mock_release
        mock_hook.set_swallow.side_effect = mock_set_swallow

        controller = LockerController(
            hook_manager=mock_hook,
            overlay_manager=mock_overlay,
            state_machine=sm,
            auto_prewarm=False,
            auto_register_signals=False,
        )

        res = controller.unlock()
        assert res is True
        assert controller.is_locked() is False
        assert controller.state == LockerState.UNLOCKED

        expected_order = [
            "state:UNLOCKING",
            "hide_overlay",
            "release_cursor",
            "swallow:False",
            "state:UNLOCKED",
        ]
        assert call_order == expected_order

    def test_lock_transition_latency_under_budget(self) -> None:
        mock_hook = MagicMock()
        mock_overlay = MagicMock()
        controller = LockerController(
            hook_manager=mock_hook,
            overlay_manager=mock_overlay,
            auto_prewarm=False,
            auto_register_signals=False,
        )

        assert controller.lock() is True
        latency_ms = controller.last_lock_latency_ms
        assert latency_ms < 200.0, f"Lock latency {latency_ms}ms exceeded 200ms budget"

        assert controller.unlock() is True
        unlock_latency_ms = controller.last_unlock_latency_ms
        assert unlock_latency_ms < 200.0, f"Unlock latency {unlock_latency_ms}ms exceeded 200ms budget"

    def test_controller_idempotency(self) -> None:
        mock_hook = MagicMock()
        mock_overlay = MagicMock()
        controller = LockerController(
            hook_manager=mock_hook,
            overlay_manager=mock_overlay,
            auto_prewarm=False,
            auto_register_signals=False,
        )

        # Initial unlock is no-op
        assert controller.unlock() is True
        mock_hook.set_swallow.assert_not_called()

        # First lock executes sequence
        assert controller.lock() is True
        assert mock_hook.set_swallow.call_count == 1

        # Second lock is no-op
        assert controller.lock() is True
        assert mock_hook.set_swallow.call_count == 1

        # First unlock executes sequence
        assert controller.unlock() is True
        assert mock_hook.set_swallow.call_count == 2

        # Second unlock is no-op
        assert controller.unlock() is True
        assert mock_hook.set_swallow.call_count == 2

    def test_controller_safe_rollback_on_failure(self) -> None:
        mock_hook = MagicMock()
        mock_overlay = MagicMock()
        # Simulate failure during show_overlay
        mock_overlay.show_overlay.side_effect = RuntimeError("Overlay DirectX error")

        controller = LockerController(
            hook_manager=mock_hook,
            overlay_manager=mock_overlay,
            auto_prewarm=False,
            auto_register_signals=False,
        )

        res = controller.lock()
        assert res is False
        # State machine must be rolled back to UNLOCKED
        assert controller.state == LockerState.UNLOCKED
        # Cursor released and swallow disabled
        mock_overlay.release_cursor.assert_called()
        mock_hook.set_swallow.assert_called_with(False)

    def test_controller_context_manager(self) -> None:
        mock_hook = MagicMock()
        mock_overlay = MagicMock()

        with LockerController(
            hook_manager=mock_hook,
            overlay_manager=mock_overlay,
            auto_prewarm=False,
            auto_register_signals=False,
        ) as ctrl:
            assert ctrl is not None
            mock_hook.start.assert_called_once()

        mock_hook.stop.assert_called_once()
        mock_overlay.close.assert_called_once()

    def test_live_controller_integration_cycle(self) -> None:
        """Integration test with live HookManager and Win32 OverlayManager."""
        controller = LockerController(
            overlay_backend="win32",
            auto_prewarm=True,
            auto_register_signals=False,
        )
        try:
            controller.start()
            assert controller.is_locked() is False
            assert controller.state == LockerState.UNLOCKED

            # Live lock transition
            assert controller.lock() is True
            assert controller.is_locked() is True
            assert controller.state == LockerState.LOCKED
            assert controller.is_swallowing() is True
            assert controller.last_lock_latency_ms < 200.0
            assert controller.overlay_manager.is_overlay_visible() is True
            assert controller.overlay_manager.is_cursor_confined() is True

            # Live unlock transition
            assert controller.unlock() is True
            assert controller.is_locked() is False
            assert controller.state == LockerState.UNLOCKED
            assert controller.is_swallowing() is False
            assert controller.last_unlock_latency_ms < 200.0
            assert controller.overlay_manager.is_overlay_visible() is False
            assert controller.overlay_manager.is_cursor_confined() is False
        finally:
            controller.stop()

    def test_controller_hotkey_dispatch(self) -> None:
        """Verifies F11 and Ctrl+Alt+Shift+U hotkeys trigger controller lock/unlock."""
        mock_overlay = MagicMock()
        controller = LockerController(
            overlay_manager=mock_overlay,
            auto_prewarm=False,
            auto_register_signals=False,
        )
        ef = controller.hook_manager.event_filter
        mock_kb = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb)

        # Initial state: UNLOCKED
        assert controller.is_locked() is False

        # 1. Trigger F11
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_F11))
        assert controller.is_locked() is True

        # 2. Trigger Ctrl+Alt+Shift+U
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_CONTROL))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_MENU))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_SHIFT))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_U))

        import time
        for _ in range(50):
            if not controller.is_locked():
                break
            time.sleep(0.01)

        assert controller.is_locked() is False
        assert controller.state == LockerState.UNLOCKED




# ============================================================================
# 3. Keyup Leak Bugfix Unit Tests (src/input_locker/hooks/event_filter.py)
# ============================================================================

class TestKeyupLeakBugfix:
    """Tests for the keyup leak bugfix:
    
    When Ctrl+Alt+Shift+U is triggered, currently held keys are recorded in
    _pending_unlock_keyups, and subsequent WM_KEYUP / WM_SYSKEYUP events for
    those keys are swallowed even if swallow_active is False.
    """

    def test_keyup_leak_prevention_on_unlock_combo(self) -> None:
        unlock_called = []
        ef = EventFilter(
            on_unlock_hotkey=lambda: unlock_called.append(True),
            swallow_active=True,
        )
        mock_kb = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb)

        # 1. User holds Ctrl, Alt, Shift, then presses U
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_CONTROL))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_MENU))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_SHIFT))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_U))

        assert len(unlock_called) == 1
        # Check that pending keyups recorded all 4 keys
        pending = ef.pending_unlock_keyups
        assert VK_U in pending
        assert bool(pending & CTRL_KEYS)
        assert bool(pending & ALT_KEYS)
        assert bool(pending & SHIFT_KEYS)

        # 2. Simulate controller unlocking: swallow_active becomes False
        ef.set_swallow(False)
        assert ef.is_swallowing() is False

        # Reset mock to count ONLY post-unlock keyup swallows
        mock_kb.reset_mock()
        swallow_count_before = ef.swallowed_keyboard_count

        # 3. User releases keys one by one:
        # Release U
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_U))
        assert mock_kb.suppress_event.call_count == 1
        assert VK_U not in ef.pending_unlock_keyups

        # Release Shift
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_SHIFT))
        assert mock_kb.suppress_event.call_count == 2
        assert not bool(ef.pending_unlock_keyups & SHIFT_KEYS)

        # Release Alt (WM_SYSKEYUP)
        ef.keyboard_event_filter(WM_SYSKEYUP, MockEventData(VK_MENU))
        assert mock_kb.suppress_event.call_count == 3
        assert not bool(ef.pending_unlock_keyups & ALT_KEYS)

        # Release Ctrl
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_CONTROL))
        assert mock_kb.suppress_event.call_count == 4
        assert not bool(ef.pending_unlock_keyups & CTRL_KEYS)

        # All pending keyups should now be consumed
        assert len(ef.pending_unlock_keyups) == 0
        assert ef.swallowed_keyboard_count == swallow_count_before + 4

        # 4. Now that pending keyups are consumed, normal keystrokes PASS THROUGH
        mock_kb.reset_mock()
        res_down = ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(0x41))  # 'A' down
        res_up = ef.keyboard_event_filter(WM_KEYUP, MockEventData(0x41))      # 'A' up
        assert res_down is True
        assert res_up is True
        mock_kb.suppress_event.assert_not_called()

    def test_keyup_leak_with_left_and_right_modifier_codes(self) -> None:
        """Tests that Left Ctrl/Alt/Shift release correctly clears pending set."""
        unlock_called = []
        ef = EventFilter(
            on_unlock_hotkey=lambda: unlock_called.append(True),
            swallow_active=True,
        )
        mock_kb = MagicMock()
        ef.set_listeners(keyboard_listener=mock_kb)

        # Send Left modifiers
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_LCONTROL))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockEventData(VK_LMENU))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_LSHIFT))
        ef.keyboard_event_filter(WM_KEYDOWN, MockEventData(VK_U))

        assert len(unlock_called) == 1

        # Unlock transition
        ef.set_swallow(False)
        mock_kb.reset_mock()

        # Release generic modifier codes
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_CONTROL))
        ef.keyboard_event_filter(WM_SYSKEYUP, MockEventData(VK_MENU))
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_SHIFT))
        ef.keyboard_event_filter(WM_KEYUP, MockEventData(VK_U))

        # All 4 releases must have been suppressed
        assert mock_kb.suppress_event.call_count == 4
        assert len(ef.pending_unlock_keyups) == 0


# ============================================================================
# 4. CLI Argument Parsing and Setup Tests
# ============================================================================

class TestMainCLI:
    """Tests for main.py CLI argument parser and initialization."""

    def test_cli_default_args(self) -> None:
        args = parse_args([])
        assert args.backend in ("win32", "pyqt")
        assert args.alpha == 120
        assert args.udp_port == 9000
        assert args.tcp_port == 9001
        assert args.no_network is False
        assert args.daemon is False
        assert args.verbose is False

    def test_cli_custom_args(self) -> None:
        args = parse_args([
            "--backend", "pyqt",
            "--alpha", "180",
            "--udp-port", "9990",
            "--tcp-port", "9991",
            "--no-network",
            "--daemon",
            "--verbose",
        ])
        assert args.backend == "pyqt"
        assert args.alpha == 180
        assert args.udp_port == 9990
        assert args.tcp_port == 9991
        assert args.no_network is True
        assert args.daemon is True
        assert args.verbose is True

    def test_setup_logging_levels(self) -> None:
        with patch.object(logging, "basicConfig") as mock_basic_config:
            setup_logging(verbose=True)
            mock_basic_config.assert_called_with(
                level=logging.DEBUG,
                format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            )
            setup_logging(verbose=False)
            mock_basic_config.assert_called_with(
                level=logging.INFO,
                format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            )
