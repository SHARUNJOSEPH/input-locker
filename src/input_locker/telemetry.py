"""Anonymous, privacy-compliant usage telemetry for Input Locker using Aptabase.

Features:
- Zero Personal Identifiable Information (no IP logging, no MAC/hardware serials, no usernames).
- Distinguishes install source: 'microsoft_store' vs 'github'.
- Completely non-blocking (runs on daemon background thread with strict 3.5s timeout).
- Offline-safe (silently ignores connection errors).
- Opt-out capable via config.telemetry_enabled.
"""
from __future__ import annotations

import datetime
import json
import logging
import platform
import threading
import urllib.request
import uuid
from typing import Any, Dict, Optional

from input_locker import __version__
from input_locker.config import LockerConfig
from input_locker.updater import is_windows_store

logger = logging.getLogger(__name__)

APTABASE_APP_KEY = "A-US-7876388880"
APTABASE_ENDPOINT = "https://us.aptabase.com/api/v0/events"
_REQUEST_TIMEOUT = 3.5


def get_install_source() -> str:
    """Return 'microsoft_store' if running in MSIX container, else 'github'."""
    return "microsoft_store" if is_windows_store() else "github"


def _send_aptabase_event(event_name: str, props: Optional[Dict[str, Any]] = None) -> bool:
    """Send an anonymous telemetry event to Aptabase.

    Returns:
        bool: True if event was accepted, False otherwise.
    """
    if not APTABASE_APP_KEY:
        return False

    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    session_id = str(uuid.uuid4())

    system_props = {
        "locale": "en-US",
        "osName": "Windows",
        "osVersion": platform.release(),
        "deviceModel": platform.machine(),
        "isDebug": False,
        "appVersion": __version__,
        "sdkVersion": f"input-locker@{__version__}",
    }

    event_payload = [
        {
            "timestamp": now_utc,
            "sessionId": session_id,
            "eventName": event_name,
            "systemProps": system_props,
            "props": props or {},
        }
    ]

    try:
        data = json.dumps(event_payload).encode("utf-8")
        req = urllib.request.Request(
            APTABASE_ENDPOINT,
            data=data,
            headers={
                "App-Key": APTABASE_APP_KEY,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            return resp.status in (200, 201, 202)
    except Exception as exc:
        logger.debug("Telemetry dispatch failed (offline or unreachable): %s", exc)
        return False


def record_startup_telemetry(cfg: LockerConfig, async_mode: bool = True) -> None:
    """Record startup telemetry events (first-time install and session start).

    Checks config.telemetry_enabled and config.install_recorded.
    """
    if not getattr(cfg, "telemetry_enabled", True):
        return

    def _worker():
        source = get_install_source()
        is_first_install = not getattr(cfg, "install_recorded", False)

        if is_first_install:
            logger.info("Recording one-time anonymous install ping (source: %s)...", source)
            success = _send_aptabase_event(
                "app_installed",
                props={
                    "source": source,
                    "version": __version__,
                },
            )
            if success:
                cfg.install_recorded = True
                try:
                    cfg.save()
                except Exception as e:
                    logger.debug("Failed to persist install_recorded flag: %s", e)

        # Record session start event
        _send_aptabase_event(
            "app_started",
            props={
                "source": source,
                "version": __version__,
            },
        )

    if async_mode:
        t = threading.Thread(target=_worker, name="TelemetryWorker", daemon=True)
        t.start()
    else:
        _worker()
