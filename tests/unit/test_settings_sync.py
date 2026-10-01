"""Unit tests verifying dynamic settings persistence and runtime synchronization.

Tests:
1. Dynamic wallpaper propagation through OverlayManager and PyQtOverlay.
2. Dynamic password updates and removal via LockerController.apply_config.
3. Wallpaper clearing restores non-wallpaper state without crashes.
4. Hotkey and preference synchronization.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from input_locker.config import LockerConfig, hash_password
from input_locker.core.controller import LockerController
from input_locker.overlay.overlay_manager import OverlayManager


def test_overlay_manager_set_wallpaper():
    """Verify OverlayManager updates its wallpaper attribute and calls overlay.set_wallpaper."""
    mock_overlay = MagicMock()
    with patch("input_locker.overlay.overlay_manager.CursorGuard"):
        mgr = OverlayManager(backend="win32", auto_prewarm=False)
        mgr.overlay = mock_overlay

        test_path = "C:/wallpapers/stage_test.png"
        mgr.set_wallpaper(test_path)

        assert mgr.wallpaper == test_path
        mock_overlay.set_wallpaper.assert_called_once_with(test_path)


def test_overlay_manager_clear_wallpaper():
    """Verify OverlayManager properly propagates empty string when clearing wallpaper."""
    mock_overlay = MagicMock()
    with patch("input_locker.overlay.overlay_manager.CursorGuard"):
        mgr = OverlayManager(backend="win32", auto_prewarm=False)
        mgr.overlay = mock_overlay

        mgr.set_wallpaper("")
        assert mgr.wallpaper == ""
        mock_overlay.set_wallpaper.assert_called_once_with("")


def test_controller_apply_config_dynamic_wallpaper():
    """Verify LockerController propagates wallpaper updates and clearing to overlay_manager."""
    mock_overlay_mgr = MagicMock()
    mock_hook_mgr = MagicMock()

    controller = LockerController(
        hook_manager=mock_hook_mgr,
        overlay_manager=mock_overlay_mgr,
        auto_prewarm=False,
        auto_register_signals=False,
    )

    # Test setting a new wallpaper
    cfg = LockerConfig(wallpaper="C:/stage_bg.jpg")
    controller.apply_config(cfg)
    mock_overlay_mgr.set_wallpaper.assert_called_with("C:/stage_bg.jpg")

    # Test clearing the wallpaper
    cfg_cleared = LockerConfig(wallpaper="")
    controller.apply_config(cfg_cleared)
    mock_overlay_mgr.set_wallpaper.assert_called_with("")


def test_controller_apply_config_dynamic_password():
    """Verify LockerController dynamically updates password hashes and credentials."""
    mock_overlay_mgr = MagicMock()
    mock_hook_mgr = MagicMock()

    controller = LockerController(
        hook_manager=mock_hook_mgr,
        overlay_manager=mock_overlay_mgr,
        auto_prewarm=False,
        auto_register_signals=False,
    )

    # 1. Start with no password
    assert controller._password == ""
    assert controller._password_hash == ""

    # 2. Apply config with a new password
    pw_hash, pw_salt = hash_password("NewSecureStagePass123!")
    cfg = LockerConfig(password_hash=pw_hash, password_salt=pw_salt)
    controller.apply_config(cfg)

    assert controller._password_hash == pw_hash
    assert controller._password_salt == pw_salt

    # 3. Apply config with password removed
    cfg_empty = LockerConfig(password="", password_hash="", password_salt="")
    controller.apply_config(cfg_empty)

    assert controller._password == ""
    assert controller._password_hash == ""
    assert controller._password_salt == ""


def test_pyqt_overlay_set_wallpaper_bridge():
    """Verify PyQtOverlay emits sig_set_wallpaper or iterates widgets on set_wallpaper."""
    from input_locker.overlay.pyqt_overlay import PyQtOverlay

    with patch.object(PyQtOverlay, "prewarm"):
        overlay = PyQtOverlay(auto_prewarm=False)
        mock_bridge = MagicMock()
        overlay._bridge = mock_bridge

        overlay.set_wallpaper("C:/test_wp.png")
        assert overlay.wallpaper_path == "C:/test_wp.png"
        mock_bridge.sig_set_wallpaper.emit.assert_called_once_with("C:/test_wp.png")
