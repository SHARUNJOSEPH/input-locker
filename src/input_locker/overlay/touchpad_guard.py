"""Windows Precision Touchpad hardware & gesture toggle guard.

Cuts the Windows Precision Touchpad (PTP) and multi-finger shell gestures while the
locker is active, and restores them on unlock. Two layers are used:

1. User-scoped registry values plus WM_SETTINGCHANGE (non-elevated). This turns the
   gesture settings off, but Windows does not always honour it for swipes in flight.
2. Device-level disable of the touchpad HID device through PnP. This is what actually
   stops 3/4-finger swipes. It needs administrator rights.

The installer registers an on-demand, highest-privilege scheduled task for the
touchpad helper. At launch the app starts that task with ``schtasks /Run`` — no
UAC prompt. Lock/unlock then send commands over a small command file under
``%PROGRAMDATA%\\InputLocker``. Portable / non-installed runs fall back to a
one-shot ``RunAs`` launch (UAC once per session).

``TouchpadGuard.device_control_enabled`` is OFF by default so tests never trigger
UAC. The application entrypoint turns it on and starts the helper.

The instance IDs of any touchpad we disable are written to a small state file BEFORE
the disable runs. If the process dies while locked, ``recover_if_stale()`` re-enables
them on the next start.
"""

from __future__ import annotations

import atexit
import base64
import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Dict, List, Optional
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

# Device lookup: catch the mouse half AND the Precision Touchpad / digitizer
# sibling that feeds Shell gestures. Exclude real touchscreens so we do not
# disable a display digitizer.
_TOUCHPAD_MATCH = (
    r"touch ?pad|track ?pad|synaptics|elan|alps|goodix|"
    r"precision.?touch|hid.?compliant.?touch|hid.?digitizer"
)
_TOUCHSCREEN_MATCH = r"touch ?screen|touch.?display|pen.?digitizer|stylus"
_TOUCHPAD_CLASSES = ("Mouse", "HIDClass", "Keyboard")  # common PTP classes

_CREATE_NO_WINDOW = 0x08000000
_UAC_TIMEOUT_S = 180
_HELPER_ACK_TIMEOUT_S = 15.0
_HELPER_POLL_S = 0.05
_SCHEDULED_TASK_NAME = r"\InputLocker\InputLockerTouchpadHelper"


def _state_dir() -> Path:
    """Shared IPC directory for the elevated helper and the user-mode app.

    Prefer ``%PROGRAMDATA%\\InputLocker`` when it exists (created by the
    installer with ACLs that let Authenticated Users write cmd/ack files).
    Fall back to ``%LOCALAPPDATA%\\InputLocker`` for portable / source runs.
    """
    prog = os.environ.get("PROGRAMDATA")
    if prog:
        shared = Path(prog) / "InputLocker"
        if shared.is_dir():
            return shared
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "InputLocker"


def _state_file() -> Path:
    return _state_dir() / "touchpad_disabled.json"


def _cmd_file() -> Path:
    return _state_dir() / "touchpad_cmd.txt"


def _ack_file() -> Path:
    return _state_dir() / "touchpad_ack.txt"


def _helper_pid_file() -> Path:
    return _state_dir() / "touchpad_helper.pid"


def _read_state() -> List[str]:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        ids = data.get("touchpad_instance_ids", [])
        return [str(i) for i in ids if i]
    except FileNotFoundError:
        return []
    except Exception as exc:
        logger.warning("Could not read touchpad state file: %s", exc)
        return []


def _write_state(ids: List[str]) -> None:
    try:
        path = _state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"touchpad_instance_ids": list(ids)}), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not write touchpad state file: %s", exc)


def _clear_state() -> None:
    try:
        _state_file().unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("Could not remove touchpad state file: %s", exc)


def _ps_list(ids: List[str]) -> str:
    return ",".join("'" + i.replace("'", "''") + "'" for i in ids)


def _run_powershell(script: str, elevated: bool, timeout: float) -> subprocess.CompletedProcess:
    """Run a PowerShell script. When elevated, it is launched via UAC (RunAs)."""
    if not elevated:
        args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    else:
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        outer = (
            "try { $p = Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait -PassThru "
            "-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','"
            + encoded
            + "'; exit $p.ExitCode } catch { exit 1 }"
        )
        args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", outer]
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
        check=False,
    )


def _find_touchpad_ids() -> List[str]:
    """Instance IDs of present, healthy touchpad / PTP digitizer devices.

    Returns devices matching the touchpad name pattern whose Class is one of
    the common PTP classes, excluding touchscreens. Does not need admin.
    Logs every candidate so a failed cut can be diagnosed from the log.
    """
    class_filter = "|".join(_TOUCHPAD_CLASSES)
    script = (
        "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
        "Where-Object { "
        "$_.Status -eq 'OK' -and "
        "$_.FriendlyName -match '" + _TOUCHPAD_MATCH + "' -and "
        "$_.FriendlyName -notmatch '" + _TOUCHSCREEN_MATCH + "' -and "
        "$_.Class -match '^(" + class_filter + ")$' "
        "} | ForEach-Object { "
        "Write-Output ('{0}|{1}|{2}' -f $_.InstanceId, $_.Class, $_.FriendlyName) "
        "}"
    )
    result = _run_powershell(script, elevated=False, timeout=30)
    ids: List[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        dev_id, cls, name = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not dev_id:
            continue
        ids.append(dev_id)
        logger.info("Touchpad candidate: class=%s name=%s id=%s", cls, name, dev_id)
    if not ids:
        logger.info("No touchpad candidates matched the broadened lookup")
    return ids


def _device_statuses(ids: List[str]) -> Dict[str, str]:
    """Current PnP status per instance ID ('Missing' if the device is gone)."""
    if not ids:
        return {}
    script = (
        "foreach ($i in @(" + _ps_list(ids) + ")) { "
        "$d = Get-PnpDevice -InstanceId $i -ErrorAction SilentlyContinue; "
        "if ($d) { Write-Output ('{0}|{1}' -f $i, $d.Status) } "
        "else { Write-Output ('{0}|Missing' -f $i) } }"
    )
    result = _run_powershell(script, elevated=False, timeout=30)
    statuses: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "|" in line:
            dev_id, status = line.split("|", 1)
            statuses[dev_id.strip()] = status.strip()
    return statuses


def _disable_script(ids: List[str]) -> str:
    return (
        "$ErrorActionPreference='SilentlyContinue'; "
        "foreach ($i in @(" + _ps_list(ids) + ")) { "
        "Disable-PnpDevice -InstanceId $i -Confirm:$false }; exit 0"
    )


def _enable_script(ids: List[str]) -> str:
    return (
        "$ErrorActionPreference='SilentlyContinue'; "
        "foreach ($i in @(" + _ps_list(ids) + ")) { "
        "Enable-PnpDevice -InstanceId $i -Confirm:$false }; exit 0"
    )


def _helper_script(cmd_path: str, ack_path: str, pid_path: str) -> str:
    """Long-lived elevated PowerShell that executes disable/enable/quit commands."""
    # Paths are escaped for single-quoted PowerShell strings.
    cmd_q = cmd_path.replace("'", "''")
    ack_q = ack_path.replace("'", "''")
    pid_q = pid_path.replace("'", "''")
    return f"""
$ErrorActionPreference = 'SilentlyContinue'
$cmdPath = '{cmd_q}'
$ackPath = '{ack_q}'
$pidPath = '{pid_q}'
Set-Content -Path $pidPath -Value $PID -Encoding ASCII
while ($true) {{
    if (Test-Path -LiteralPath $cmdPath) {{
        try {{
            $raw = Get-Content -LiteralPath $cmdPath -Raw -ErrorAction Stop
            Remove-Item -LiteralPath $cmdPath -Force -ErrorAction SilentlyContinue
        }} catch {{
            Start-Sleep -Milliseconds 50
            continue
        }}
        $line = ($raw -split "`r?`n")[0]
        if (-not $line) {{ continue }}
        $parts = $line.Split('|')
        $action = $parts[0]
        $ids = @()
        if ($parts.Length -gt 1 -and $parts[1]) {{
            $ids = $parts[1].Split(';') | Where-Object {{ $_ }}
        }}
        if ($action -eq 'quit') {{
            Set-Content -Path $ackPath -Value 'ok|quit' -Encoding ASCII
            Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
            break
        }}
        if ($action -eq 'disable') {{
            foreach ($i in $ids) {{ Disable-PnpDevice -InstanceId $i -Confirm:$false }}
            Set-Content -Path $ackPath -Value 'ok|disable' -Encoding ASCII
            continue
        }}
        if ($action -eq 'enable') {{
            foreach ($i in $ids) {{ Enable-PnpDevice -InstanceId $i -Confirm:$false }}
            Set-Content -Path $ackPath -Value 'ok|enable' -Encoding ASCII
            continue
        }}
        Set-Content -Path $ackPath -Value ('err|unknown|' + $action) -Encoding ASCII
    }}
    Start-Sleep -Milliseconds 50
}}
"""


def _helper_alive() -> bool:
    try:
        pid = int(_helper_pid_file().read_text(encoding="utf-8").strip())
    except Exception:
        return False
    try:
        # OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION; None/0 handle => dead
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    return False


class TouchpadGuard:
    """Manages cutting and restoring the Windows Precision Touchpad and gestures."""

    # Set True by the application entrypoint. Device disable needs UAC, so it is
    # opt-in; when False only the registry cut is applied.
    device_control_enabled: bool = False

    _original_status_enabled: Optional[int] = None
    _original_gestures: Dict[str, int] = {}
    _is_cut: bool = False
    _disabled_device_ids: List[str] = []
    _device_worker = None
    _helper_started: bool = False
    # Pre-discovered at startup so lock does not wait on Get-PnpDevice.
    _cached_touchpad_ids: List[str] = []

    @classmethod
    def is_cut(cls) -> bool:
        """Returns True if the touchpad is currently cut."""
        return cls._is_cut

    @classmethod
    def _scheduled_task_exists(cls) -> bool:
        """True if the install-time elevated scheduled task is registered."""
        try:
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", _SCHEDULED_TASK_NAME],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    @classmethod
    def _start_helper_via_scheduled_task(cls) -> bool:
        """Start the helper through the install-time task (no UAC)."""
        try:
            result = subprocess.run(
                ["schtasks", "/Run", "/TN", _SCHEDULED_TASK_NAME],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
            if result.returncode != 0:
                logger.debug(
                    "schtasks /Run failed (rc=%s): %s",
                    result.returncode,
                    (result.stderr or result.stdout or "").strip(),
                )
                return False
            deadline = time.time() + _HELPER_ACK_TIMEOUT_S
            while time.time() < deadline:
                if _helper_alive():
                    cls._helper_started = True
                    logger.info(
                        "Touchpad elevated helper started via scheduled task (no UAC)"
                    )
                    return True
                time.sleep(_HELPER_POLL_S)
            logger.warning("Scheduled-task touchpad helper did not start in time")
            return False
        except Exception as exc:
            logger.debug("Scheduled-task helper start error: %s", exc)
            return False

    @classmethod
    def _start_helper_via_runas(cls) -> bool:
        """Fallback: one-shot elevated PowerShell (shows UAC). For portable runs."""
        try:
            script = _helper_script(
                str(_cmd_file()),
                str(_ack_file()),
                str(_helper_pid_file()),
            )
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            outer = (
                "try { Start-Process powershell -Verb RunAs -WindowStyle Hidden "
                "-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','"
                + encoded
                + "'; exit 0 } catch { exit 1 }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", outer],
                capture_output=True,
                text=True,
                timeout=_UAC_TIMEOUT_S,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
            if result.returncode != 0:
                logger.warning("Failed to launch elevated touchpad helper (UAC declined?)")
                return False

            deadline = time.time() + _HELPER_ACK_TIMEOUT_S
            while time.time() < deadline:
                if _helper_alive():
                    cls._helper_started = True
                    logger.info(
                        "Touchpad elevated helper started via RunAs (UAC once this session)"
                    )
                    return True
                time.sleep(_HELPER_POLL_S)
            logger.warning("Elevated touchpad helper did not start in time")
            return False
        except Exception as exc:
            logger.warning("RunAs helper start error: %s", exc)
            return False

    @classmethod
    def ensure_elevated_helper(cls) -> bool:
        """Start the once-per-session elevated helper without a UAC prompt when possible.

        Prefer the install-time scheduled task (``schtasks /Run``). Fall back to a
        one-shot ``RunAs`` launch only when the task is missing (portable / source).

        Call from the application entrypoint after enabling device control.
        Returns True if the helper is running (already was, or just started).
        """
        if not cls.device_control_enabled:
            return False
        if _helper_alive():
            cls._helper_started = True
            logger.info("Touchpad elevated helper already running")
            return True

        try:
            _state_dir().mkdir(parents=True, exist_ok=True)
            for p in (_cmd_file(), _ack_file()):
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
                except Exception:
                    pass

            if cls._scheduled_task_exists():
                if cls._start_helper_via_scheduled_task():
                    return True
                logger.warning(
                    "Scheduled-task helper start failed; falling back to RunAs (UAC)"
                )

            return cls._start_helper_via_runas()
        except Exception as exc:
            logger.warning("ensure_elevated_helper error: %s", exc)
            return False

    @classmethod
    def stop_elevated_helper(cls) -> None:
        """Ask the elevated helper to quit. Best-effort; safe to call at exit."""
        if not cls._helper_started and not _helper_alive():
            return
        try:
            cls._send_helper_command("quit", [], timeout=3.0)
        except Exception as exc:
            logger.debug("stop_elevated_helper error: %s", exc)
        cls._helper_started = False
        try:
            _helper_pid_file().unlink()
        except Exception:
            pass

    @classmethod
    def _send_helper_command(cls, action: str, ids: List[str], timeout: float = _HELPER_ACK_TIMEOUT_S) -> bool:
        """Send disable/enable/quit to the elevated helper and wait for ack."""
        if not _helper_alive():
            return False
        try:
            _state_dir().mkdir(parents=True, exist_ok=True)
            try:
                _ack_file().unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass
            payload = action + "|" + ";".join(ids)
            # Write to a temp name then rename so the helper never reads a partial file.
            tmp = _cmd_file().with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(_cmd_file())

            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    ack = _ack_file().read_text(encoding="utf-8").strip()
                    if ack.startswith("ok|"):
                        try:
                            _ack_file().unlink()
                        except Exception:
                            pass
                        return True
                    if ack.startswith("err|"):
                        logger.warning("Touchpad helper returned error: %s", ack)
                        return False
                except FileNotFoundError:
                    pass
                except Exception:
                    pass
                time.sleep(_HELPER_POLL_S)
            logger.warning("Touchpad helper did not acknowledge '%s' in time", action)
            return False
        except Exception as exc:
            logger.warning("Touchpad helper command '%s' failed: %s", action, exc)
            return False

    @classmethod
    def cut_touchpad(cls) -> bool:
        """Cut the touchpad and multi-finger gestures while system is locked."""
        try:
            # 1. Back up and disable Status\\Enabled
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

            # 3. Disable the touchpad device itself (elevated, opt-in).
            # Registry cut above is near-instant; PnP discovery + Disable-PnpDevice
            # can take several seconds, so run that on a background thread so the
            # lock overlay can appear immediately. Unlock joins the worker before
            # restoring so we never re-enable mid-cut.
            if cls.device_control_enabled:
                cls._start_device_cut_async()

            # 4. Broadcast WM_SETTINGCHANGE so Windows Shell applies it immediately
            cls._notify_system()
            logger.info("Precision Touchpad and gestures cut successfully")
            return True
        except Exception as exc:
            logger.warning("cut_touchpad error: %s", exc)
            return False

    @classmethod
    def restore_touchpad(cls) -> bool:
        """Restore touchpad and multi-finger gestures upon unlock."""
        # Wait for any in-flight device disable so we re-enable what it actually disabled.
        cls._join_device_worker()
        if not cls._is_cut:
            if cls._disabled_device_ids:
                cls._restore_devices()
            return True
        try:
            # 1. Restore Status\\Enabled
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

            # 3. Re-enable the touchpad device (elevated)
            if cls._disabled_device_ids:
                cls._restore_devices()

            # 4. Broadcast WM_SETTINGCHANGE
            cls._notify_system()
            logger.info("Precision Touchpad and gestures restored successfully")
            return True
        except Exception as exc:
            logger.warning("restore_touchpad error: %s", exc)
            return False

    @classmethod
    def recover_if_stale(cls) -> bool:
        """Re-enable touchpad devices left disabled by a previous crashed session.

        Call once at startup, before any lock happens. Combines:
        1. Instance IDs recorded in the crash-recovery state file.
        2. Any present touchpad-like device whose Status is not OK (e.g. Error /
           Disabled) — covers the case where the process was killed before the
           state file was written, or only a subset was recorded.
        """
        ids = list(_read_state())
        known = set(ids)

        # Also hunt for currently-disabled touchpad devices so a hard kill
        # (Alt+F4 on the console, Task Manager End Task) never leaves the
        # touchpad permanently dead.
        try:
            class_filter = "|".join(_TOUCHPAD_CLASSES)
            script = (
                "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
                "Where-Object { "
                "$_.Status -ne 'OK' -and "
                "$_.FriendlyName -match '" + _TOUCHPAD_MATCH + "' -and "
                "$_.FriendlyName -notmatch '" + _TOUCHSCREEN_MATCH + "' -and "
                "$_.Class -match '^(" + class_filter + ")$' "
                "} | ForEach-Object { $_.InstanceId }"
            )
            result = _run_powershell(script, elevated=False, timeout=30)
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and line not in known:
                    ids.append(line)
                    known.add(line)
                    logger.warning("Found stuck-disabled touchpad device: %s", line)
        except Exception as exc:
            logger.debug("Stuck-touchpad scan failed: %s", exc)

        if not ids:
            return True
        logger.warning(
            "Touchpad was left disabled by a previous session; re-enabling %d device(s)",
            len(ids),
        )
        cls._disabled_device_ids = ids
        return cls._restore_devices()

    @classmethod
    def _start_device_cut_async(cls) -> None:
        """Run _cut_devices on a daemon thread, tracked so restore can join it."""
        import threading

        worker = threading.Thread(target=cls._cut_devices, name="TouchpadDeviceCut", daemon=True)
        cls._device_worker = worker
        worker.start()

    @classmethod
    def _join_device_worker(cls, timeout: float = _UAC_TIMEOUT_S + 10) -> None:
        worker = cls._device_worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)
        cls._device_worker = None

    @classmethod
    def warm_device_cache(cls) -> List[str]:
        """Pre-discover touchpad instance IDs so the first lock is not blocked on PnP.

        Safe to call at startup (non-elevated). Returns the cached ID list.
        """
        if cls._cached_touchpad_ids:
            return list(cls._cached_touchpad_ids)
        try:
            ids = _find_touchpad_ids()
        except Exception as exc:
            logger.warning("Touchpad device cache warm-up failed: %s", exc)
            return []
        cls._cached_touchpad_ids = list(ids)
        if ids:
            logger.info("Touchpad device cache warmed: %d candidate(s)", len(ids))
        else:
            logger.info("Touchpad device cache warmed: no candidates found")
        return list(ids)

    @classmethod
    def _cut_devices(cls) -> None:
        """Disable the touchpad device(s). Prefer the session helper; else one-shot UAC."""
        if cls._disabled_device_ids:
            return  # already cut
        ids = list(cls._cached_touchpad_ids)
        if not ids:
            try:
                ids = _find_touchpad_ids()
            except Exception as exc:
                logger.warning("Touchpad device lookup failed: %s", exc)
                return
            if ids:
                cls._cached_touchpad_ids = list(ids)
        if not ids:
            logger.info("No active touchpad device found; relying on registry cut only")
            return

        # Persist BEFORE disabling so a crash mid-way is repaired on next start.
        _write_state(ids)

        used_helper = False
        if _helper_alive() or cls.ensure_elevated_helper():
            used_helper = cls._send_helper_command("disable", ids)
            if used_helper:
                logger.info("Touchpad disable sent via elevated helper")

        if not used_helper:
            # Fallback: one-shot elevated PowerShell (shows UAC).
            try:
                _run_powershell(_disable_script(ids), elevated=True, timeout=_UAC_TIMEOUT_S)
            except Exception as exc:
                logger.warning("Elevated touchpad disable did not complete: %s", exc)
                cls._disabled_device_ids = ids
                return

        # Helper ack already means Disable-PnpDevice ran; skip a second Get-PnpDevice
        # status round-trip when we can (saves ~1–4 s on the background worker).
        if used_helper:
            cls._disabled_device_ids = list(ids)
            _write_state(ids)
            logger.info("Touchpad device(s) disabled via helper: %d", len(ids))
            return

        statuses = _device_statuses(ids)
        still_active = [i for i, st in statuses.items() if st == "OK"]
        disabled = [i for i in ids if i not in still_active]
        for i in ids:
            logger.info(
                "Touchpad cut result: id=%s status=%s",
                i,
                statuses.get(i, "unknown"),
            )
        if disabled:
            cls._disabled_device_ids = disabled
            _write_state(disabled)
            logger.info("Touchpad device(s) disabled: %d of %d", len(disabled), len(ids))
        else:
            _clear_state()
            logger.warning("Touchpad device could not be disabled (UAC declined or failed)")

    @classmethod
    def _restore_devices(cls) -> bool:
        """Re-enable any touchpad device we disabled. Keeps the record if it fails."""
        ids = list(cls._disabled_device_ids)
        if not ids:
            return True

        used_helper = False
        if _helper_alive():
            used_helper = cls._send_helper_command("enable", ids)
            if used_helper:
                logger.info("Touchpad enable sent via elevated helper")

        if not used_helper:
            try:
                _run_powershell(_enable_script(ids), elevated=True, timeout=_UAC_TIMEOUT_S)
            except Exception as exc:
                logger.warning("Elevated touchpad enable did not complete: %s", exc)
                return False

        remaining = [
            i for i, st in _device_statuses(ids).items() if st not in ("OK", "Missing")
        ]
        if remaining:
            cls._disabled_device_ids = remaining
            _write_state(remaining)
            logger.warning("Touchpad device(s) still disabled: %d", len(remaining))
            return False

        cls._disabled_device_ids = []
        _clear_state()
        return True

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
atexit.register(TouchpadGuard.stop_elevated_helper)
