"""System tray icon for Windows AV Staging Input Locker.

Generates a simple padlock icon with Pillow and hosts it via pystray.
Runs in a daemon thread so the icon stops automatically when the process exits.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_ICON_SIZE = 64
_COLOR_LOCKED   = (220, 50,  50,  255)
_COLOR_UNLOCKED = (50,  200, 50,  255)
_COLOR_SHACKLE  = (30,  30,  30,  255)
_COLOR_BODY_FG  = (255, 255, 255, 255)


def _draw_padlock(locked: bool):
    from pathlib import Path
    from PIL import Image

    # Check for professional generated icon assets
    from input_locker.config import get_assets_dir
    assets_dir = get_assets_dir()
    target_asset = assets_dir / ("tray_locked.png" if locked else "tray_unlocked.png")
    if target_asset.is_file():
        try:
            return Image.open(str(target_asset)).convert("RGBA")
        except Exception:
            pass

    from PIL import ImageDraw
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    body_color = _COLOR_LOCKED if locked else _COLOR_UNLOCKED

    shackle_left, shackle_right = 18, 46
    shackle_top,  shackle_bot   = 4,  30

    if locked:
        draw.arc([shackle_left, shackle_top, shackle_right, shackle_bot],
                 start=180, end=0, fill=_COLOR_SHACKLE, width=6)
        draw.line([(shackle_left + 3,  (shackle_top + shackle_bot) // 2),
                   (shackle_left + 3,  shackle_bot - 2)], fill=_COLOR_SHACKLE, width=6)
        draw.line([(shackle_right - 3, (shackle_top + shackle_bot) // 2),
                   (shackle_right - 3, shackle_bot - 2)], fill=_COLOR_SHACKLE, width=6)
    else:
        draw.arc([shackle_left, shackle_top, shackle_right, shackle_bot],
                 start=180, end=0, fill=_COLOR_SHACKLE, width=6)
        draw.line([(shackle_right - 3, (shackle_top + shackle_bot) // 2),
                   (shackle_right - 3, shackle_bot - 2)], fill=_COLOR_SHACKLE, width=6)

    draw.rounded_rectangle([10, 28, 54, 58], radius=6, fill=body_color)
    kx, ky = 32, 40
    draw.ellipse([kx - 5, ky - 5, kx + 5, ky + 5], fill=_COLOR_BODY_FG)
    draw.rectangle([kx - 3, ky + 2, kx + 3, ky + 10], fill=_COLOR_BODY_FG)
    return img


class TrayIcon:
    """System tray icon with Lock / Unlock / Exit menu items."""

    def __init__(
        self,
        on_lock:   Callable[[], None],
        on_unlock: Callable[[], None],
        on_exit:   Callable[[], None],
    ) -> None:
        self._on_lock   = on_lock
        self._on_unlock = on_unlock
        self._on_exit   = on_exit
        self._icon: Optional[object] = None
        self._thread: Optional[threading.Thread] = None

    def _menu_lock(self, icon, item) -> None:
        threading.Thread(target=self._on_lock,   daemon=True, name="TrayLockThread").start()

    def _menu_unlock(self, icon, item) -> None:
        threading.Thread(target=self._on_unlock, daemon=True, name="TrayUnlockThread").start()

    def _menu_check_updates(self, icon, item) -> None:
        def _on_result(update_info):
            from input_locker import __version__
            if update_info:
                ver = update_info.get("latest_version", "")
                self.notify(
                    "Update Available",
                    f"A new version of Input Locker ({ver}) is available!\nVisit GitHub releases to download.",
                )
            else:
                self.notify(
                    "Input Locker Up to Date",
                    f"You are running the latest version (v{__version__}).",
                )

        from input_locker.updater import check_for_updates_async
        from input_locker.config import LockerConfig
        cfg = LockerConfig.load()
        check_for_updates_async(callback=_on_result, repo_or_url=cfg.update_repo)

    def _menu_exit(self, icon, item) -> None:
        self._on_exit()
        icon.stop()

    def _build_menu(self):
        import pystray
        return pystray.Menu(
            pystray.MenuItem("Lock",   self._menu_lock),
            pystray.MenuItem("Unlock", self._menu_unlock),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Check for Updates...", self._menu_check_updates),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit",   self._menu_exit),
        )

    def start(self) -> None:
        try:
            import pystray
        except ImportError:
            logger.warning("pystray not installed - tray icon disabled. Run: pip install pystray Pillow")
            return

        img = _draw_padlock(locked=False)
        self._icon = pystray.Icon(
            name="InputLocker",
            icon=img,
            title="Input Locker — Ready",
            menu=self._build_menu(),
        )
        self._thread = threading.Thread(
            target=self._icon.run, daemon=True, name="TrayIconThread"
        )
        self._thread.start()
        logger.info("System tray icon started.")

        # Show startup balloon in background so main() isn't blocked
        def _delayed_notify() -> None:
            import time
            time.sleep(0.8)  # wait for pystray to register the icon
            self.notify(
                "Input Locker is running",
                "Press F11 to lock.  Right-click this tray icon to Lock / Unlock / Exit.\n"
                "Tip: if you don't see this icon, click the  ^  arrow in the taskbar.",
            )

        threading.Thread(target=_delayed_notify, daemon=True,
                         name="TrayNotifyThread").start()

    def notify(self, title: str, message: str) -> None:
        """Show a Windows tray balloon notification."""
        if self._icon is None:
            return
        try:
            # pystray >= 0.19 exposes notify()
            self._icon.notify(message, title)
        except Exception:
            # Fallback: ctypes balloon via Shell_NotifyIcon NIM_MODIFY
            try:
                self._ctypes_balloon(title, message)
            except Exception as exc:
                logger.debug("Balloon notification failed: %s", exc)

    @staticmethod
    def _ctypes_balloon(title: str, message: str) -> None:
        """Win32 Shell_NotifyIcon balloon fallback (no third-party deps)."""
        import ctypes, ctypes.wintypes as wt
        NIIF_INFO  = 0x00000001
        NIF_INFO   = 0x00000010
        NIM_MODIFY = 0x00000001

        class NOTIFYICONDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize",           wt.DWORD),
                ("hWnd",             wt.HWND),
                ("uID",              wt.UINT),
                ("uFlags",           wt.UINT),
                ("uCallbackMessage", wt.UINT),
                ("hIcon",            wt.HICON),
                ("szTip",            wt.WCHAR * 128),
                ("dwState",          wt.DWORD),
                ("dwStateMask",      wt.DWORD),
                ("szInfo",           wt.WCHAR * 256),
                ("uTimeout",         wt.UINT),
                ("szInfoTitle",      wt.WCHAR * 64),
                ("dwInfoFlags",      wt.DWORD),
            ]
        nid = NOTIFYICONDATA()
        nid.cbSize      = ctypes.sizeof(NOTIFYICONDATA)
        nid.uFlags      = NIF_INFO
        nid.szInfo      = message[:255]
        nid.szInfoTitle = title[:63]
        nid.dwInfoFlags = NIIF_INFO
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def update_state(self, locked: bool) -> None:
        if self._icon is None:
            return
        try:
            self._icon.icon  = _draw_padlock(locked=locked)
            self._icon.title = "Input Locker — LOCKED" if locked else "Input Locker — Ready"
        except Exception as exc:
            logger.debug("Tray icon update failed: %s", exc)

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass

