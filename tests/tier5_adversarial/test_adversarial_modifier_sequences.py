"""Tier 5 Adversarial Test Suite: Modifier Sequences & Hotkey Edge Cases.

Adversarial stress-testing of low-level hook event filtering:
- Asymmetric modifier combinations (L/R Ctrl, L/R Alt, L/R Shift)
- Interleaved noise keys between modifier activations
- Rapid F11 key-repeat storm and debounce resilience
- Stuck modifier cleanup across lock/unlock transitions
- Keyup leak prevention for unlock combo keys
- Malformed / corrupted KBDLLHOOKSTRUCT data structures
"""

from __future__ import annotations

import types
from typing import List
import pytest

from input_locker.hooks.event_filter import (
    EventFilter,
    VK_CONTROL,
    VK_LCONTROL,
    VK_RCONTROL,
    VK_MENU,
    VK_LMENU,
    VK_RMENU,
    VK_SHIFT,
    VK_LSHIFT,
    VK_RSHIFT,
    VK_F11,
    VK_U,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
    SuppressException,
)


class MockKbdHookStruct:
    """Simulates Windows KBDLLHOOKSTRUCT."""

    def __init__(self, vk_code: int, scan_code: int = 0, flags: int = 0) -> None:
        self.vkCode = vk_code
        self.scanCode = scan_code
        self.flags = flags


class TestAdversarialModifierSequences:
    """Adversarial testing of hook event filtering under complex modifier patterns."""

    def test_asymmetric_modifier_combinations_trigger_unlock(self) -> None:
        """Verify all combinations of Left/Right modifiers successfully trigger unlock."""
        unlock_calls = 0

        def on_unlock() -> None:
            nonlocal unlock_calls
            unlock_calls += 1

        combinations = [
            (VK_LCONTROL, VK_LMENU, VK_LSHIFT),
            (VK_RCONTROL, VK_RMENU, VK_RSHIFT),
            (VK_LCONTROL, VK_RMENU, VK_LSHIFT),
            (VK_RCONTROL, VK_LMENU, VK_RSHIFT),
            (VK_CONTROL, VK_MENU, VK_SHIFT),
            (VK_LCONTROL, VK_MENU, VK_RSHIFT),
        ]

        for ctrl_vk, alt_vk, shift_vk in combinations:
            unlock_calls = 0
            mock_listener = types.SimpleNamespace(suppress_event=lambda: None)
            ef = EventFilter(on_unlock_hotkey=on_unlock, swallow_active=True)
            ef.set_listeners(keyboard_listener=mock_listener)

            # Press modifiers
            ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(ctrl_vk))
            ef.keyboard_event_filter(WM_SYSKEYDOWN, MockKbdHookStruct(alt_vk))
            ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(shift_vk))

            # Press 'U'
            ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(VK_U))

            assert unlock_calls == 1, (
                f"Failed unlock on combo ({hex(ctrl_vk)}, {hex(alt_vk)}, {hex(shift_vk)})"
            )

    def test_missing_single_modifier_permutations_do_not_unlock(self) -> None:
        """Adversarially test all permutations where exactly 1 required modifier is missing."""
        unlock_calls = 0

        def on_unlock() -> None:
            nonlocal unlock_calls
            unlock_calls += 1

        ef = EventFilter(on_unlock_hotkey=on_unlock, swallow_active=True)

        partial_combos = [
            # Missing Shift
            [(VK_CONTROL, WM_KEYDOWN), (VK_MENU, WM_SYSKEYDOWN)],
            # Missing Ctrl
            [(VK_MENU, WM_SYSKEYDOWN), (VK_SHIFT, WM_KEYDOWN)],
            # Missing Alt
            [(VK_CONTROL, WM_KEYDOWN), (VK_SHIFT, WM_KEYDOWN)],
            # Only Ctrl
            [(VK_CONTROL, WM_KEYDOWN)],
            # Only Alt
            [(VK_MENU, WM_SYSKEYDOWN)],
            # Only Shift
            [(VK_SHIFT, WM_KEYDOWN)],
        ]

        for combo in partial_combos:
            ef.set_swallow(True)
            for vk, msg in combo:
                try:
                    ef.keyboard_event_filter(msg, MockKbdHookStruct(vk))
                except SuppressException:
                    pass

            # Press 'U'
            try:
                ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(VK_U))
            except SuppressException:
                pass

            assert unlock_calls == 0, f"Partial combo unexpectedly unlocked: {combo}"

            # Release keys
            for vk, msg in combo:
                up_msg = WM_SYSKEYUP if msg == WM_SYSKEYDOWN else WM_KEYUP
                try:
                    ef.keyboard_event_filter(up_msg, MockKbdHookStruct(vk))
                except SuppressException:
                    pass

    def test_interleaved_noise_keys_before_u_trigger(self) -> None:
        """Verify unlock triggers even if un-held noise keys occurred during modifier setup."""
        unlock_calls = 0

        def on_unlock() -> None:
            nonlocal unlock_calls
            unlock_calls += 1

        ef = EventFilter(on_unlock_hotkey=on_unlock, swallow_active=True)
        ef.set_listeners(keyboard_listener=types.SimpleNamespace(suppress_event=lambda: None))

        # Ctrl down
        ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(VK_LCONTROL))
        # Noise key 'A' down and up
        ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(0x41))
        ef.keyboard_event_filter(WM_KEYUP, MockKbdHookStruct(0x41))
        # Alt down
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockKbdHookStruct(VK_LMENU))
        # Noise key 'B' down and up
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockKbdHookStruct(0x42))
        ef.keyboard_event_filter(WM_SYSKEYUP, MockKbdHookStruct(0x42))
        # Shift down
        ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(VK_LSHIFT))

        # 'U' down
        ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(VK_U))

        assert unlock_calls == 1

    def test_rapid_f11_auto_repeat_storm(self) -> None:
        """Stress-test rapid keyboard auto-repeat (50 consecutive F11 keydowns)."""
        lock_calls = 0

        def on_lock() -> None:
            nonlocal lock_calls
            lock_calls += 1

        ef = EventFilter(on_lock_hotkey=on_lock, swallow_active=False)

        # Simulate keyboard auto-repeat storm
        for _ in range(50):
            with pytest.raises(SuppressException):
                ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(VK_F11))

        assert lock_calls == 50
        assert ef.swallowed_keyboard_count == 50

    def test_pending_unlock_keyup_swallow_behavior(self) -> None:
        """Verify that when unlock occurs, release of combo keys is swallowed to prevent leak."""
        suppressed_count = 0

        def on_suppress():
            nonlocal suppressed_count
            suppressed_count += 1

        ef = EventFilter(swallow_active=True)
        ef.set_listeners(keyboard_listener=types.SimpleNamespace(suppress_event=on_suppress))

        # Setup combo: Ctrl + Alt + Shift + U
        ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(VK_CONTROL))
        ef.keyboard_event_filter(WM_SYSKEYDOWN, MockKbdHookStruct(VK_MENU))
        ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(VK_SHIFT))

        # Press 'U' -> triggers combo and registers pending keyups
        ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(VK_U))

        # Simulate controller unlocking: swallow_active becomes False
        ef.set_swallow(False)
        assert ef.swallow_active is False

        # Releasing 'U' should be swallowed via pending_unlock_keyups
        count_before = suppressed_count
        ef.keyboard_event_filter(WM_KEYUP, MockKbdHookStruct(VK_U))
        assert suppressed_count == count_before + 1

        # Subsequent normal typing must NOT be swallowed
        res = ef.keyboard_event_filter(WM_KEYDOWN, MockKbdHookStruct(0x41))  # 'A'
        assert res is True

    def test_corrupted_kbd_data_structures(self) -> None:
        """Verify event filter resilience against corrupted or unexpected data structures."""
        ef = EventFilter(swallow_active=False)

        # Raw integer
        res1 = ef.keyboard_event_filter(WM_KEYDOWN, 0x41)
        assert res1 is True

        # Dictionary
        res2 = ef.keyboard_event_filter(WM_KEYDOWN, {"vkCode": 0x42})
        assert res2 is True

        # Object with no vkCode
        res3 = ef.keyboard_event_filter(WM_KEYDOWN, object())
        assert res3 is True

        # None data
        res4 = ef.keyboard_event_filter(WM_KEYDOWN, None)
        assert res4 is True

        # F11 as int when unlocked should still swallow
        with pytest.raises(SuppressException):
            ef.keyboard_event_filter(WM_KEYDOWN, VK_F11)

    def test_mouse_filter_event_counting_under_stress(self) -> None:
        """Verify mouse event filter swallows and counts thousands of high-rate events."""
        ef = EventFilter(swallow_active=True)

        # 500 mouse moves while locked
        for i in range(500):
            with pytest.raises(SuppressException):
                ef.mouse_event_filter(0x0200, None)

        assert ef.swallowed_mouse_count == 500
        assert ef.total_mouse_count == 500

        # Unlock and verify passthrough
        ef.set_swallow(False)
        for i in range(100):
            res = ef.mouse_event_filter(0x0200, None)
            assert res is True

        assert ef.swallowed_mouse_count == 500
        assert ef.total_mouse_count == 600
