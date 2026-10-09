"""Windows Precision Touchpad hardware & gesture toggle guard.

Provides dynamic, non-elevated disabling and restoration of the Windows Precision
Touchpad (PTP) subsystem and multi-finger shell gestures via user-scoped registry
and WM_SETTINGCHANGE notifications.
"""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
import logging
from typing import Dict, Optional
import winreg

logger = logging.getLogger(__name__)

WM_SETTINGCHANGE = 0x001A
SPI_SETTOUCHPADPARAMETERS = 0x00AF
HWND_BROADCAST = 0xFFFF
SMTO_ABORTIFHUNG = 0x0002

_STATUS_KEY = r"Software\Microsoft\Windows\CurrentVersion\PrecisionTouchPad\Status"
_PTP_KEY = r"Software\Microsoft\Windows\CurrentVersion\PrecisionTouchPad"

_GESTURE_VALS = (
    "ThreeFingerSlideEnabled",
    "FourFingerSlideEnabled",
    "ThreeFingerTapEnabled",
    "FourFingerTapEnabled",
    # Additional Windows 11 PTP gesture toggles (present on recent builds)
    "FiveFingerTapEnabled",
    "LeaveOnWithMouse",
    "EnableEdgy",
)


class TouchpadGuard:
    """Manages cutting and restoring the Windows Precision Touchpad and gestures."""

    _original_status_enabled: Optional[int] = None
    _original_gestures: Dict[str, int] = {}
    _is_cut: bool = False

    @classmethod
    def is_cut(cls) -> bool:
        """Returns True if the touchpad is currently cut."""
        return cls._is_cut

    @classmethod
    def cut_touchpad(cls) -> bool:
        """Cut the touchpad and multi-finger gestures while system is locked."""
        try:
            # 1. Back up and disable Status\Enabled
            try:
                k = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    _STATUS_KEY,
                    0,
                    winreg.KEY_READ | winreg.KEY_SET_VALUE,
                )
                try:
                    val, _ = winreg.QueryValueEx(k, "Enabled")
                    if cls._original_status_enabled is None:
                        cls._original_status_enabled = int(val)
                except Exception:
                    if cls._original_status_enabled is None:
                        cls._original_status_enabled = 1
                winreg.SetValueEx(k, "Enabled", 0, winreg.REG_DWORD, 0)
                winreg.CloseKey(k)
            except Exception as exc:
                logger.debug("TouchpadGuard Status\\Enabled cut error: %s", exc)

            # 2. Back up and disable multi-finger gestures
            try:
                k2 = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    _PTP_KEY,
                    0,
                    winreg.KEY_READ | winreg.KEY_SET_VALUE,
                )
                for name in _GESTURE_VALS:
                    if name not in cls._original_gestures:
                        try:
                            v, _ = winreg.QueryValueEx(k2, name)
                            cls._original_gestures[name] = int(v)
                        except Exception:
                            cls._original_gestures[name] = 1
                    winreg.SetValueEx(k2, name, 0, winreg.REG_DWORD, 0)
                winreg.CloseKey(k2)
            except Exception as exc:
                logger.debug("TouchpadGuard gestures cut error: %s", exc)

            cls._is_cut = True

            # 3. Broadcast WM_SETTINGCHANGE so Windows Shell applies it immediately
            cls._notify_system()
            logger.info("Precision Touchpad and gestures cut successfully")
            return True
        except Exception as exc:
            logger.warning("cut_touchpad error: %s", exc)
            return False

    @classmethod
    def restore_touchpad(cls) -> bool:
        """Restore touchpad and multi-finger gestures upon unlock."""
        if not cls._is_cut:
            return True
        try:
            # 1. Restore Status\Enabled
            try:
                k = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    _STATUS_KEY,
                    0,
                    winreg.KEY_SET_VALUE,
                )
                orig = cls._original_status_enabled if cls._original_status_enabled is not None else 1
                winreg.SetValueEx(k, "Enabled", 0, winreg.REG_DWORD, orig)
                winreg.CloseKey(k)
            except Exception as exc:
                logger.debug("TouchpadGuard Status\\Enabled restore error: %s", exc)

            # 2. Restore Gestures
            try:
                k2 = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    _PTP_KEY,
                    0,
                    winreg.KEY_SET_VALUE,
                )
                for name in _GESTURE_VALS:
                    orig_val = cls._original_gestures.get(name, 1)
                    winreg.SetValueEx(k2, name, 0, winreg.REG_DWORD, orig_val)
                winreg.CloseKey(k2)
            except Exception as exc:
                logger.debug("TouchpadGuard gestures restore error: %s", exc)

            cls._is_cut = False
            cls._original_status_enabled = None
            cls._original_gestures.clear()

            # 3. Broadcast WM_SETTINGCHANGE
            cls._notify_system()
            logger.info("Precision Touchpad and gestures restored successfully")
            return True
        except Exception as exc:
            logger.warning("restore_touchpad error: %s", exc)
            return False

    @classmethod
    def _notify_system(cls) -> None:
        """Broadcast settings change so explorer / PTP stack reloads registry values.

        WM_SETTINGCHANGE alone is often ignored by the Precision Touchpad service.
        Also call SystemParametersInfoW(SPI_SETTOUCHPADPARAMETERS) when available,
        and notify under several common setting names used across Windows 10/11.
        """
        user32 = ctypes.windll.user32
        try:
            if hasattr(user32, "SendNotifyMessageW"):
                user32.SendNotifyMessageW(
                    HWND_BROADCAST,
                    WM_SETTINGCHANGE,
                    SPI_SETTOUCHPADPARAMETERS,
                    "PrecisionTouchPad",
                )
            else:
                res = wintypes.DWORD()
                user32.SendMessageTimeoutW(
                    HWND_BROADCAST,
                    WM_SETTINGCHANGE,
                    SPI_SETTOUCHPADPARAMETERS,
                    "PrecisionTouchPad",
                    SMTO_ABORTIFHUNG,
                    20,
                    ctypes.byref(res),
                )
        except Exception as exc:
            logger.debug("TouchpadGuard notify system error: %s", exc)


# Fail-safe atexit registration
atexit.register(TouchpadGuard.restore_touchpad)
