"""CLI Launcher and Entry Point for Windows AV Staging Input Locker.

Provides options for overlay backend (win32 or pyqt), network control ports,
daemon mode, and verbosity settings.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import signal
import sys
import threading
import time
from typing import List, Optional

# Ensure src root is on sys.path when invoked directly
_src_root = str(Path(__file__).resolve().parent.parent)
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from input_locker import __version__
# NOTE: LockerController (and its PyQt6 / pynput deps) are imported lazily
# inside main() so the settings dialog appears immediately on startup.

logger = logging.getLogger("input_locker")


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for Input Locker."""
    parser = argparse.ArgumentParser(
        prog="input-locker",
        description=(
            "Windows AV Staging Input Locker: Global keyboard/mouse suppression "
            "with non-activating semi-transparent visual pass-through overlay."
        ),
    )

    parser.add_argument(
        "--backend",
        choices=["win32", "pyqt"],
        default="pyqt",
        help="Overlay rendering backend: 'pyqt' (default, styled badge) or 'win32' (featherweight).",
    )
    parser.add_argument(
        "--alpha",
        type=int,
        default=120,
        help="Overlay opacity (0=fully transparent, 255=opaque). Default: 120",
    )
    parser.add_argument(
        "--udp-port",
        type=int,
        default=9000,
        help="OSC over UDP show control port. Default: 9000",
    )
    parser.add_argument(
        "--tcp-port",
        type=int,
        default=9001,
        help="JSON over TCP automation and health check port. Default: 9001",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Network interface to bind (default: 127.0.0.1 for localhost only). Use 0.0.0.0 or --bind-all for LAN AV staging.",
    )
    parser.add_argument(
        "--bind-all",
        action="store_true",
        help="Bind network server to all interfaces (0.0.0.0) to allow remote AV console control over LAN.",
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Disable network remote control listeners.",
    )
    parser.add_argument(
        "--password",
        type=str,
        default="",
        metavar="TEXT",
        help=(
            "Set a password required to unlock via hotkey or tray menu. "
            "If omitted, no password is required. "
            "Note: the password is stored in process memory as plaintext."
        ),
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Open the settings GUI to change wallpaper / password before launching.",
    )
    parser.add_argument(
        "--lock",
        action="store_true",
        default=False,
        help="Immediately lock the screen upon launch.",
    )
    parser.add_argument(
        "--no-lock",
        action="store_true",
        default=False,
        help="Do not lock the screen upon launch; run in background awaiting F11.",
    )
    parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Run as a persistent background daemon process.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program version and exit.",
    )

    return parser.parse_args(args)


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging format and level."""
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    logging.basicConfig(level=log_level, format=log_format)


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI execution routine."""
    args = parse_args(argv)
    setup_logging(args.verbose)

    # ── Windows Taskbar AppUserModelID Setup ─────────────────────────────
    # Ensures Windows displays the application icon on the taskbar instead of python.exe
    try:
        import ctypes
        myappid = f"SharunJoseph.InputLocker.App.{__version__}"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception as exc:
        logger.debug("Could not set AppUserModelID: %s", exc)

    # ── Single-instance enforcement ─────────────────────────────────────────
    from input_locker.core.single_instance import SingleInstanceManager
    single_instance = SingleInstanceManager()
    if not single_instance.acquire():
        logger.info("Another instance of Input Locker is already running. Focusing existing instance.")
        single_instance.notify_existing_instance()
        return 0

    logger.info("Starting Windows AV Staging Input Locker v%s...", __version__)
    logger.info("Overlay backend: %s (alpha=%d)", args.backend, args.alpha)

    # ── Configuration loading ──────────────────────────────────────────────
    from input_locker.config import LockerConfig
    locker_cfg = LockerConfig.load()

    # Always show the Settings GUI on startup so the user sees the Lock button.
    # Skip only when --no-lock is passed from an automated/daemon context, or --daemon.
    skip_gui = args.daemon
    if not skip_gui:
        try:
            from input_locker.ui.config_gui import show_config_dialog
            cfg, should_launch = show_config_dialog(config=locker_cfg)
            if not should_launch or cfg is None:
                logger.info("Settings dialog cancelled — exiting.")
                return 0
            locker_cfg = cfg
        except Exception as exc:
            logger.warning("Settings dialog failed (%s) — launching with defaults.", exc)

    # CLI args take precedence over saved config
    effective_password  = args.password or locker_cfg.password
    effective_hash      = locker_cfg.password_hash
    effective_salt      = locker_cfg.password_salt
    effective_wallpaper = getattr(args, "wallpaper", "") or locker_cfg.wallpaper

    should_lock = False
    if args.lock:
        should_lock = True
    elif args.no_lock:
        should_lock = False
    else:
        should_lock = getattr(locker_cfg, "lock_on_launch", True)

    effective_lock_hotkey = getattr(locker_cfg, "lock_hotkey", "F11")
    effective_unlock_hotkey = getattr(locker_cfg, "unlock_hotkey", "Ctrl+Alt+Shift+U")
    effective_audio_feedback = getattr(locker_cfg, "audio_feedback", False)

    pwd_suffix = " (password protected)" if (effective_password or effective_hash) else ""
    logger.info("Lock Hotkey: %s | Unlock Combo: %s%s", effective_lock_hotkey, effective_unlock_hotkey, pwd_suffix)
    if effective_audio_feedback:
        logger.info("Audio Feedback: Enabled (Acoustic confirmation cues)")

    # ── System tray icon ───────────────────────────────────────────────────
    tray = None
    try:
        from input_locker.ui.tray_icon import TrayIcon
        _tray_ref: list = []   # mutable container so lambdas can reach the controller

        def _tray_unlock():
            if _tray_ref:
                _tray_ref[0]._on_unlock_requested()

        def _tray_exit():
            shutdown_event.set()

        tray = TrayIcon(
            on_lock=lambda: _tray_ref[0].lock() if _tray_ref else None,
            on_unlock=_tray_unlock,
            on_exit=_tray_exit,
        )
        tray.start()
    except Exception as exc:
        logger.warning("Tray icon could not start: %s", exc)

    # ── State change callback — updates tray icon ──────────────────────────
    def _on_state_change(locked: bool) -> None:
        if tray is not None:
            tray.update_state(locked)

    # ── Controller ─────────────────────────────────────────────────────────
    # Import here (lazy) so PyQt6 / pynput only load after the settings dialog
    from input_locker.core.controller import LockerController

    controller = LockerController(
        overlay_backend=args.backend,
        alpha=args.alpha,
        auto_prewarm=True,
        password=effective_password,
        password_hash=effective_hash,
        password_salt=effective_salt,
        wallpaper=effective_wallpaper,
        on_state_change=_on_state_change,
        audio_feedback=effective_audio_feedback,
        lock_hotkey=effective_lock_hotkey,
        unlock_hotkey=effective_unlock_hotkey,
    )
    if tray is not None:
        _tray_ref.append(controller)   # now the tray lambdas can reach the controller

    # Optional network server integration (Milestone 4)
    network_server = None
    if not args.no_network:
        try:
            from input_locker.network.server import NetworkController
            effective_host = "0.0.0.0" if args.bind_all else args.host  # nosec B104
            network_server = NetworkController(
                controller=controller,
                udp_port=args.udp_port,
                tcp_port=args.tcp_port,
                host=effective_host,
            )
            logger.info(
                "Network show control enabled (%s): OSC UDP=%d, JSON TCP=%d",
                effective_host,
                args.udp_port,
                args.tcp_port,
            )
        except ImportError:
            logger.info(
                "Network subsystem (input_locker.network) not installed; running in hotkey-only mode."
            )

    shutdown_event = threading.Event()

    def _signal_handler(signum: int, frame: object) -> None:
        logger.info("Shutdown signal (%s) received; stopping...", signum)
        shutdown_event.set()

    # Register termination handlers in main thread
    if threading.current_thread() is threading.main_thread():
        try:
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)
            if hasattr(signal, "SIGBREAK"):
                signal.signal(signal.SIGBREAK, _signal_handler)
        except (ValueError, AttributeError):
            pass

    try:
        controller.start()
        if network_server is not None:
            network_server.start()

        if should_lock:
            logger.info("Auto-locking screen on startup...")
            time.sleep(0.3)
            controller.lock()
            logger.info("Input Locker is ACTIVE — Screen is LOCKED.")
        else:
            logger.info("Input Locker is ACTIVE and ready (Press F11 to Lock).")

        logger.info("Press Ctrl+C in this terminal to exit.")

        # Listen for secondary instance launch events (e.g. desktop shortcut double-click)
        reopen_settings_event = threading.Event()
        single_instance.start_listener(
            on_request_callback=lambda: reopen_settings_event.set(),
            shutdown_event=shutdown_event,
        )

        # Main wait loop
        while not shutdown_event.is_set():
            if reopen_settings_event.is_set():
                reopen_settings_event.clear()
                if not controller.is_locked:
                    from input_locker.core.single_instance import focus_existing_window
                    if not focus_existing_window():
                        try:
                            from input_locker.ui.config_gui import show_config_dialog
                            cfg, _ = show_config_dialog(config=locker_cfg)
                            if cfg is not None:
                                locker_cfg = cfg
                        except Exception as exc:
                            logger.warning("Could not reopen settings: %s", exc)

            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt detected.")
    finally:
        logger.info("Shutting down Input Locker subsystems...")
        single_instance.release()
        if network_server is not None:
            try:
                network_server.stop()
            except Exception as exc:
                logger.warning("Error stopping network server: %s", exc)

        controller.stop()

        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass

        logger.info("Input Locker terminated cleanly.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
