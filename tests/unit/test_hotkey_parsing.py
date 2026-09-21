"""Unit tests for hotkey parsing, validation, and matching."""

import pytest
from input_locker.hooks import VK_F11
from input_locker.hooks.hotkey import (
    HotkeyBinding,
    parse_hotkey,
    LOCK_HOTKEY_PRESETS,
    UNLOCK_HOTKEY_PRESETS,
    CTRL_KEYS,
    ALT_KEYS,
    SHIFT_KEYS,
)


class TestHotkeyParsing:
    """Validate hotkey parser with standard and custom combinations."""

    def test_parse_single_function_key(self):
        binding = parse_hotkey("F11")
        assert binding.vk == 0x7A
        assert not binding.ctrl
        assert not binding.alt
        assert not binding.shift
        assert binding.format() == "F11"

    def test_parse_function_keys_range(self):
        for i in range(1, 13):
            binding = parse_hotkey(f"F{i}")
            assert binding.vk == 0x6F + i
            assert binding.format() == f"F{i}"

    def test_parse_modifiers_combo(self):
        binding = parse_hotkey("Ctrl + Alt + Shift + U")
        assert binding.vk == ord("U")
        assert binding.ctrl is True
        assert binding.alt is True
        assert binding.shift is True
        assert binding.format() == "Ctrl+Alt+Shift+U"

    def test_parse_case_insensitivity(self):
        binding = parse_hotkey("ctrl+alt+l")
        assert binding.vk == ord("L")
        assert binding.ctrl is True
        assert binding.alt is True
        assert binding.format() == "Ctrl+Alt+L"

    def test_parse_empty_string_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_hotkey("")

    def test_parse_only_modifiers_raises(self):
        with pytest.raises(ValueError, match="Missing base key"):
            parse_hotkey("Ctrl+Alt")

    def test_parse_unknown_key_raises(self):
        with pytest.raises(ValueError, match="Unknown key"):
            parse_hotkey("Ctrl+FooBarKey")

    def test_parse_multiple_base_keys_raises(self):
        with pytest.raises(ValueError, match="Multiple base keys"):
            parse_hotkey("Ctrl+A+B")

    def test_binding_matching(self):
        binding = parse_hotkey("Ctrl+F12")
        active = {0x11}  # VK_CONTROL
        assert binding.matches(0x7B, active) is True  # F12 + Ctrl
        assert binding.matches(0x7A, active) is False  # Wrong VK
        assert binding.matches(0x7B, set()) is False   # Missing Ctrl

    def test_presets_are_valid(self):
        for p in LOCK_HOTKEY_PRESETS:
            b = parse_hotkey(p)
            assert b.vk > 0
        for p in UNLOCK_HOTKEY_PRESETS:
            b = parse_hotkey(p)
            assert b.vk > 0
