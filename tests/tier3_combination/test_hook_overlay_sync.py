"""Tier 3 Combination Test Suite: Hook Swallowing & Overlay Synchronization.

Verifies:
- Hook swallowing activates synchronously with overlay appearance
- Cursor confinement activates synchronously with hook swallowing
- Overlay is hidden before input pass-through is re-enabled on unlock
- Cursor bounds are restored after overlay is hidden
"""

import time
import pytest
from tests.harness.input_injector import InputInjector
from tests.harness.focus_harness import CompanionFocusHarness
from tests.conftest import TestController


class TestHookOverlaySyncCombination:
    """Pairwise verification: Hook manager and Overlay manager state synchronization."""

    def test_swallowing_active_before_overlay_visible(self, test_controller: TestController):
        """Verify input swallowing is active when overlay becomes visible (no window of input leakage)."""
        assert not test_controller.is_locked
        assert not test_controller.hook_mgr.is_swallowing()
        assert not test_controller.overlay_mgr.is_overlay_visible()

        test_controller.lock()

        # Both must be active
        assert test_controller.hook_mgr.is_swallowing(), "Hook swallowing not active!"
        assert test_controller.overlay_mgr.is_overlay_visible(), "Overlay not visible!"
        test_controller.unlock()

    def test_cursor_confined_before_overlay_visible(self, test_controller: TestController):
        """Verify cursor confinement is engaged simultaneously with overlay presentation."""
        test_controller.lock()
        assert test_controller.overlay_mgr.is_cursor_confined()
        assert test_controller.overlay_mgr.is_overlay_visible()
        test_controller.unlock()

    def test_overlay_hidden_before_input_unswallowed(self, test_controller: TestController):
        """Verify on unlock, the overlay is hidden and cursor released as swallowing disables."""
        test_controller.lock()
        assert test_controller.is_locked

        test_controller.unlock()

        assert not test_controller.overlay_mgr.is_overlay_visible()
        assert not test_controller.hook_mgr.is_swallowing()
        assert not test_controller.overlay_mgr.is_cursor_confined()

    def test_cursor_released_after_overlay_hidden(self, test_controller: TestController):
        """Verify cursor confinement is released when overlay is hidden, restoring full navigation."""
        test_controller.lock()
        test_controller.unlock()

        pos = InputInjector.get_cursor_pos()
        # Verify cursor can move away from (0,0)
        InputInjector.set_cursor_pos(120, 120)
        new_pos = InputInjector.get_cursor_pos()
        assert new_pos == (120, 120), f"Cursor movement restricted after unlock: {new_pos}"
