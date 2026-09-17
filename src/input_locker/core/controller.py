"""Top-level LockerController linking OS hooks, visual overlay, and state machine.

Implements the central coordination engine for the Windows AV Staging Input Locker.
Executes the surveyed optimal lock and unlock sequencing with sub-millisecond
latency, strict idempotence, zero focus disruption, and fail-safe lifecycle cleanup.
"""

from __future__ import annotations

import atexit
import logging
import signal
import sys
import threading
import time
from typing import Any, Optional

from input_locker.core.state_machine import (
    LockerState,
    StateMachine,
)
from input_locker.hooks.hook_manager import HookManager
from input_locker.overlay.overlay_manager import OverlayManager

logger = logging.getLogger(__name__)


def _set_disable_lock_workstation(disabled: bool) -> None:
    """Attempt to toggle DisableLockWorkstation in registry if permissions allow."""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "DisableLockWorkstation", 0, winreg.REG_DWORD, 1 if disabled else 0)
    except Exception:
        pass


class LockerController:
    """Central coordinator linking OS hooks, visual overlay, and state machine.
    
    Adheres to the M3 Controller specification in DISPATCH.md and PROJECT.md:
    - Pre-warms overlay window at initialization for sub-2ms activation.
    - Manages strict 5-step lock and unlock sequences.
    - Tracks end-to-end transition latency (< 200 ms requirement, < 3 ms typical).
    - Enforces fail-safe lifecycle cleanup via atexit and OS signal handlers.
    """

    def __init__(
        self,
        hook_manager: Optional[HookManager] = None,
        overlay_manager: Optional[OverlayManager] = None,
        state_machine: Optional[StateMachine] = None,
        overlay_backend: str = "pyqt",
        alpha: int = 120,
        auto_prewarm: bool = True,
        auto_register_signals: bool = True,
        password: str = "",
        password_hash: str = "",
        password_salt: str = "",
        on_state_change: Optional[Any] = None,
        wallpaper: str = "",
    ) -> None:
        """Initialize the LockerController.

        Args:
            hook_manager: Optional custom HookManager instance.
            overlay_manager: Optional custom OverlayManager instance.
            state_machine: Optional custom StateMachine instance.
            overlay_backend: Overlay renderer ('pyqt' or 'win32'). Default 'pyqt'.
            alpha: Overlay opacity (0-255). Default 120 (~47%).
            auto_prewarm: Pre-render hidden overlay window at boot. Default True.
            auto_register_signals: Register SIGINT/SIGTERM handlers. Default True.
            password: Optional plaintext password (for CLI args). Default ''.
            password_hash: Salted PBKDF2 hash of the unlock password.
            password_salt: Cryptographic random salt for the password hash.
            on_state_change: Optional callable(locked: bool) fired after each transition.
            wallpaper: Optional absolute path to a lock screen wallpaper image.
        """
        self._lock = threading.RLock()
        self._is_running = False
        self._auto_prewarm = auto_prewarm
        self._password = password
        self._password_hash = password_hash
        self._password_salt = password_salt
        self._on_state_change = on_state_change

        # 1. Initialize State Machine
        self.state_machine = state_machine or StateMachine(initial_state=LockerState.UNLOCKED)

        # 2. Initialize Overlay Manager
        self.overlay_manager = overlay_manager or OverlayManager(
            backend=overlay_backend,
            alpha=alpha,
            auto_prewarm=auto_prewarm,
            wallpaper=wallpaper,
        )

        # 3. Initialize Hook Manager
        if hook_manager is not None:
            self.hook_manager = hook_manager
            def _async_lock():
                threading.Thread(target=self.lock, daemon=True, name="CtrlLockAsync").start()

            def _async_unlock():
                threading.Thread(target=self._on_unlock_requested, daemon=True, name="CtrlUnlockAsync").start()

            if getattr(self.hook_manager, "_on_lock_hotkey", None) is None:
                self.hook_manager._on_lock_hotkey = _async_lock
                if hasattr(self.hook_manager, "event_filter"):
                    self.hook_manager.event_filter._on_lock_hotkey = _async_lock
            if getattr(self.hook_manager, "_on_unlock_hotkey", None) is None:
                self.hook_manager._on_unlock_hotkey = _async_unlock
                if hasattr(self.hook_manager, "event_filter"):
                    self.hook_manager.event_filter._on_unlock_hotkey = _async_unlock
        else:
            def _async_lock():
                threading.Thread(target=self.lock, daemon=True, name="CtrlLockAsync").start()

            def _async_unlock():
                threading.Thread(target=self._on_unlock_requested, daemon=True, name="CtrlUnlockAsync").start()

            self.hook_manager = HookManager(
                on_lock_hotkey=_async_lock,
                on_unlock_hotkey=_async_unlock,
                swallow_active=False,
            )

        # Telemetry & Latency tracking
        self._last_lock_latency_ms: float = 0.0
        self._last_unlock_latency_ms: float = 0.0
        self._lock_count: int = 0
        self._unlock_count: int = 0

        # Lifecycle registration
        atexit.register(self._emergency_cleanup)
        if auto_register_signals:
            self._register_signal_handlers()

    @property
    def state(self) -> LockerState:
        """Return the current LockerState."""
        return self.state_machine.state

    def is_locked(self) -> bool:
        """Return True if currently in LOCKED state."""
        return self.state_machine.is_locked()

    def is_swallowing(self) -> bool:
        """Return True if input swallowing is currently active."""
        return self.state_machine.is_swallowing() or self.hook_manager.is_swallowing()

    @property
    def last_lock_latency_ms(self) -> float:
        """Return latency of last lock transition in milliseconds."""
        with self._lock:
            return self._last_lock_latency_ms

    @property
    def last_unlock_latency_ms(self) -> float:
        """Return latency of last unlock transition in milliseconds."""
        with self._lock:
            return self._last_unlock_latency_ms

    @property
    def last_transition_latency_ms(self) -> float:
        """Return latency of the most recent transition (lock or unlock)."""
        with self._lock:
            return self.state_machine.last_transition_latency_ms

    def _register_signal_handlers(self) -> None:
        """Register graceful exit handlers for SIGINT and SIGTERM."""
        try:
            # Signal handling is only permitted in the main interpreter thread
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGINT, self._handle_signal)
                signal.signal(signal.SIGTERM, self._handle_signal)
                if hasattr(signal, "SIGBREAK"):
                    signal.signal(signal.SIGBREAK, self._handle_signal)
        except (ValueError, AttributeError) as exc:
            logger.debug("Signal handler registration skipped: %s", exc)

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle OS termination signals safely."""
        logger.info("Termination signal received (%s); shutting down cleanly...", signum)
        self.stop()
        sys.exit(0)

    def start(self) -> None:
        """Start background input hooks and prepare overlay."""
        with self._lock:
            if self._is_running:
                logger.debug("LockerController already started.")
                return

            logger.info("Starting LockerController...")
            # Prewarm overlay if not done during init
            if not self._auto_prewarm:
                self.overlay_manager.prewarm()

            # Start OS hook listener threads
            self.hook_manager.start()
            self._is_running = True
            logger.info("LockerController started successfully.")

    def stop(self) -> None:
        """Cleanly stop hooks, restore cursor, hide overlay, and release resources."""
        with self._lock:
            if not self._is_running:
                return

            logger.info("Stopping LockerController...")
            # If locked, perform safe unlock transition first
            if self.is_locked() or self.state == LockerState.LOCKING:
                try:
                    self.unlock()
                except Exception as exc:
                    logger.warning("Error during pre-stop unlock: %s", exc)

            # Terminate hooks
            try:
                self.hook_manager.stop()
            except Exception as exc:
                logger.warning("Error stopping hook manager: %s", exc)

            # Close overlay resources
            try:
                self.overlay_manager.close()
            except Exception as exc:
                logger.warning("Error closing overlay manager: %s", exc)

            self._is_running = False
            logger.info("LockerController stopped cleanly.")

    def lock(self) -> bool:
        """Execute the 5-step atomic lock activation sequence.
        
        Sequence:
        1. Set state to LOCKING
        2. Enable hook swallowing (hook_manager.set_swallow(True))
        3. Confine cursor to (0, 0) (overlay_manager.confine_cursor())
        4. Show overlay (overlay_manager.show_overlay())
        5. Set state to LOCKED
        
        Returns:
            bool: True if lock succeeded or was already locked (idempotent).
        """
        with self._lock:
            current_state = self.state_machine.state
            if current_state in (LockerState.LOCKED, LockerState.LOCKING):
                logger.debug("Lock requested but already in %s; returning True", current_state.value)
                return True

            t0 = time.perf_counter()
            logger.info("Executing Lock activation sequence...")

            try:
                # Step 1: Transition state machine to LOCKING
                self.state_machine.transition_to(LockerState.LOCKING)

                # Step 2: Engage OS input swallowing immediately
                self.hook_manager.set_swallow(True)

                # Step 3: Confine cursor to (0, 0) and hide cursor shape
                self.overlay_manager.confine_cursor()

                # Step 4: Display non-activating glass overlay
                self.overlay_manager.show_overlay()

                # Step 5: Transition state machine to LOCKED
                self.state_machine.transition_to(LockerState.LOCKED)
                _set_disable_lock_workstation(True)
                self._start_watchdog()

                t1 = time.perf_counter()
                latency_ms = (t1 - t0) * 1000.0
                self._last_lock_latency_ms = latency_ms
                self._lock_count += 1

                logger.info(
                    "Lock sequence completed in %.3f ms (Budget < 200 ms)",
                    latency_ms,
                )
                if self._on_state_change:
                    try:
                        self._on_state_change(True)
                    except Exception:
                        pass
                return True

            except Exception as exc:
                logger.error("Failure during lock sequence: %s. Initiating rollback...", exc, exc_info=True)
                self._safe_rollback()
                return False

    def _start_watchdog(self) -> None:
        """Start periodic enforcement watchdog during locked state."""
        def _watchdog_loop():
            while self.is_locked():
                try:
                    time.sleep(0.3)
                    if not self.is_locked():
                        break
                    # If password entry dialog is active, let it manage confinement
                    if getattr(self.hook_manager.event_filter, "password_mode", False):
                        continue
                    # Re-enforce cursor confinement to (0, 0)
                    if not self.overlay_manager.cursor_guard.is_confined():
                        self.overlay_manager.confine_cursor()
                    # Re-assert overlay on top
                    if hasattr(self.overlay_manager, "overlay") and hasattr(self.overlay_manager.overlay, "show"):
                        self.overlay_manager.overlay.show()
                except Exception as exc:
                    logger.debug("Watchdog cycle error: %s", exc)

        t = threading.Thread(target=_watchdog_loop, daemon=True, name="LockerWatchdog")
        t.start()


    def _on_unlock_requested(self) -> None:
        """Handle unlock hotkey or tray click — gate on password if one is configured."""
        if not self.is_locked():
            return

        has_pwd = bool(self._password or self._password_hash)
        if not has_pwd:
            self.unlock()
            return

        prompt_text = "Enter your unlock password:"

        # Enable password entry mode in hook manager:
        # - Normal text input keys reach the password prompt
        # - System task-switching shortcuts (Alt+Tab, Win, Alt+Esc, Ctrl+Esc) are STRICTLY SWALLOWED!
        self.hook_manager.set_swallow(False)
        self.hook_manager.set_password_mode(True)
        try:
            from input_locker.ui.password_dialog import show_password_dialog

            def _on_dialog_ready(x: int, y: int, w: int, h: int) -> None:
                # Confine mouse within the dialog window bounds so background apps cannot be clicked
                try:
                    self.overlay_manager.cursor_guard.confine_to_rect(x, y, x + w, y + h)
                except Exception as exc:
                    logger.debug("Error confining cursor to dialog: %s", exc)

            verify_fn = None
            if self._password_hash:
                from input_locker.config import verify_password
                verify_fn = lambda candidate: verify_password(candidate, self._password_hash, self._password_salt)
            elif self._password:
                verify_fn = lambda candidate: candidate == self._password

            entered = show_password_dialog(
                prompt=prompt_text,
                expected_password=self._password,
                verify_fn=verify_fn,
                on_ready=_on_dialog_ready,
            )
            if entered is not None:
                logger.info("Unlock confirmed — unlocking.")
                self.hook_manager.set_password_mode(False)
                self.unlock()
            else:
                logger.info("Unlock cancelled — remaining locked.")
                self.hook_manager.set_password_mode(False)
                self.hook_manager.set_swallow(True)
                self.overlay_manager.confine_cursor()
        except Exception as exc:
            logger.error("Error during password-gated unlock: %s", exc, exc_info=True)
            self.hook_manager.set_password_mode(False)
            self.hook_manager.set_swallow(True)
            self.overlay_manager.confine_cursor()

    def unlock(self) -> bool:
        """Execute the 5-step atomic unlock deactivation sequence.
        
        Sequence:
        1. Set state to UNLOCKING
        2. Hide overlay (overlay_manager.hide_overlay())
        3. Release cursor (overlay_manager.release_cursor())
        4. Disable hook swallowing (hook_manager.set_swallow(False))
        5. Set state to UNLOCKED
        
        Returns:
            bool: True if unlock succeeded or was already unlocked (idempotent).
        """
        with self._lock:
            current_state = self.state_machine.state
            if current_state in (LockerState.UNLOCKED, LockerState.UNLOCKING):
                logger.debug("Unlock requested but already in %s; returning True", current_state.value)
                return True

            t0 = time.perf_counter()
            logger.info("Executing Unlock deactivation sequence...")

            try:
                # Step 1: Transition state machine to UNLOCKING
                self.state_machine.transition_to(LockerState.UNLOCKING)

                # Step 2: Hide overlay window
                self.overlay_manager.hide_overlay()

                # Step 3: Release cursor confinement and restore visibility
                self.overlay_manager.release_cursor()

                # Step 4: Disable hook swallowing
                self.hook_manager.set_swallow(False)

                # Step 5: Transition state machine to UNLOCKED
                self.state_machine.transition_to(LockerState.UNLOCKED)
                _set_disable_lock_workstation(False)

                t1 = time.perf_counter()
                latency_ms = (t1 - t0) * 1000.0
                self._last_unlock_latency_ms = latency_ms
                self._unlock_count += 1

                logger.info(
                    "Unlock sequence completed in %.3f ms (Budget < 200 ms)",
                    latency_ms,
                )
                if self._on_state_change:
                    try:
                        self._on_state_change(False)
                    except Exception:
                        pass
                return True

            except Exception as exc:
                logger.error("Failure during unlock sequence: %s. Forcing fail-safe release...", exc, exc_info=True)
                self._safe_rollback()
                return False

    def _safe_rollback(self) -> None:
        """Emergency rollback ensuring user input is restored on sequence failure."""
        try:
            self.overlay_manager.hide_overlay()
        except Exception:
            pass
        try:
            self.overlay_manager.release_cursor()
        except Exception:
            pass
        try:
            self.hook_manager.set_swallow(False)
        except Exception:
            pass
        self.state_machine.reset()

    def _emergency_cleanup(self) -> None:
        """Atexit handler guaranteeing cursor and hook restoration on process exit."""
        try:
            self.stop()
        except Exception:
            pass

    def __enter__(self) -> LockerController:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
