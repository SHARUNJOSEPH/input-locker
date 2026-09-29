"""Automatic version update checker and in-app installer for Input Locker.

Features:
- Offline-safe, non-blocking update discovery via GitHub Releases API.
- Microsoft Store container auto-detection (MSIX / Store compliant policy).
- Strict semantic version comparison and downgrade prevention.
- Simulation hooks via CLI args (--simulate-update-version=) and environment variables.
- Direct Windows asset (.exe setup / standalone binary) discovery.
- Threaded background downloader with real-time byte & percentage progress callbacks.
- Detached installer launcher with automatic clean process termination and restart.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from input_locker import __version__

logger = logging.getLogger(__name__)

DEFAULT_UPDATE_REPO = "SHARUNJOSEPH/input-locker"
_DEFAULT_TIMEOUT_S = 4.0


def is_windows_store() -> bool:
    """Check if the application is running inside a packaged Microsoft Store (MSIX) container."""
    if os.environ.get("WINDOWS_STORE", "").lower() in ("1", "true", "yes"):
        return True
    if "--windows-store" in sys.argv:
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            length = wintypes.UINT(0)
            ret = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
            # ERROR_SUCCESS = 0, ERROR_INSUFFICIENT_BUFFER = 122 -> Inside Store MSIX container
            # APPMODEL_ERROR_NO_PACKAGE = 15700 -> Standalone Win32
            return ret in (0, 122)
        except Exception:
            return False
    return False


def get_effective_version(default_version: str = __version__) -> str:
    """Return effective version string, supporting simulation arguments for testing."""
    for arg in sys.argv:
        if arg.startswith("--simulate-update-version="):
            return arg.split("=", 1)[1].strip()
    sim_env = os.environ.get("SIMULATE_UPDATE_VERSION", "").strip()
    if sim_env:
        return sim_env
    return default_version


def parse_version(ver_str: str) -> tuple[int, ...]:
    """Parse a semantic version string (e.g. 'v0.2.5', '1.0.0') into a numeric tuple."""
    clean = re.sub(r"^[^\d]*", "", (ver_str or "").strip())
    tokens = re.split(r"[.\-+]", clean)
    nums = []
    for t in tokens:
        if t.isdigit():
            nums.append(int(t))
        else:
            break
    return tuple(nums) or (0,)


def is_newer_version(remote_version: str, local_version: Optional[str] = None) -> bool:
    """Compare two version strings; return True if remote is strictly greater than local."""
    if local_version is None:
        local_version = get_effective_version()
    r_tuple = parse_version(remote_version)
    l_tuple = parse_version(local_version)
    # Pad to equal length for proper comparison
    max_len = max(len(r_tuple), len(l_tuple))
    r_padded = r_tuple + (0,) * (max_len - len(r_tuple))
    l_padded = l_tuple + (0,) * (max_len - len(l_tuple))
    return r_padded > l_padded


def parse_release_highlights(body: str) -> List[str]:
    """Parse release body markdown into clean, concise highlight bullet points."""
    if not body:
        return [
            "Bug fixes and overall stability improvements.",
            "Optimized input interception response time.",
            "Enhanced staging lock screen UI."
        ]

    lines = body.strip().splitlines()
    bullets = []
    for line in lines:
        cleaned = line.strip()
        if cleaned.startswith(("- ", "* ", "• ")):
            item = cleaned[2:].strip()
            if item:
                # Remove bold markers for display or format neatly
                bullets.append(item)
        elif cleaned.startswith("### "):
            header = cleaned[4:].strip()
            if header:
                bullets.append(f"{header}")

    if not bullets:
        # Fallback to non-empty lines
        for line in lines:
            cleaned = line.strip()
            if cleaned and not cleaned.startswith("#"):
                bullets.append(cleaned)
                if len(bullets) >= 4:
                    break

    return bullets[:5] or [
        "Bug fixes and stability improvements.",
        "Performance optimization."
    ]


def check_for_updates(
    repo_or_url: str = "",
    current_version: Optional[str] = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> Optional[Dict[str, Any]]:
    """Query release source for newer version with Store-awareness and downgrade prevention.

    Args:
        repo_or_url: 'owner/repo' for GitHub Releases, or a full URL to a release JSON.
        current_version: Current application version string (defaults to effective version).
        timeout: Network timeout in seconds (default 4.0).

    Returns:
        Dict with update metadata or None if network check fails.
    """
    cur_ver = current_version or get_effective_version()
    is_store = is_windows_store()

    if is_store:
        return {
            "is_store": True,
            "has_update": False,
            "available": False,
            "current_version": cur_ver,
            "latest_version": cur_ver,
            "message": "Updates are managed automatically by the Microsoft Store.",
            "release_name": f"Input Locker v{cur_ver}",
            "release_notes": "",
            "release_url": "",
            "direct_download_url": "",
            "highlights": ["Store updates are installed automatically in the background."]
        }

    repo = repo_or_url.strip() or DEFAULT_UPDATE_REPO
    if repo.startswith("https://"):
        endpoint = repo
    elif repo.startswith("http://"):
        logger.warning("Insecure HTTP update URL rejected: %s", repo)
        return None
    else:
        endpoint = f"https://api.github.com/repos/{repo}/releases/latest"

    # Enforce HTTPS scheme for security
    if not endpoint.startswith("https://"):
        logger.warning("Non-HTTPS update endpoint rejected for security: %s", endpoint)
        return None

    try:
        req = urllib.request.Request(
            endpoint,
            headers={
                "User-Agent": f"InputLocker/{cur_ver}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))

        tag_name = data.get("tag_name", "") or data.get("version", "")
        if not tag_name:
            return None

        latest_clean = tag_name.lstrip("v")
        has_update = is_newer_version(latest_clean, cur_ver)

        # Extract direct Windows setup/installer asset ONLY if an update is available
        direct_download_url = ""
        assets = data.get("assets", [])
        if has_update and isinstance(assets, list):
            # Prioritize Setup executable (Inno Setup), then any .exe, then .zip
            setup_asset = None
            for a in assets:
                name = (a.get("name") or "").lower()
                if name.endswith(".exe") and "setup" in name:
                    setup_asset = a
                    break
            if not setup_asset:
                for a in assets:
                    name = (a.get("name") or "").lower()
                    if name.endswith(".exe"):
                        setup_asset = a
                        break
            if not setup_asset:
                for a in assets:
                    name = (a.get("name") or "").lower()
                    if name.endswith(".zip") and ("windows" in name or "win64" in name):
                        setup_asset = a
                        break

            if setup_asset:
                direct_download_url = setup_asset.get("browser_download_url", "")

        raw_body = (data.get("body", "") or "").strip()
        highlights = parse_release_highlights(raw_body)
        release_url = data.get("html_url", f"https://github.com/{repo}/releases/latest")

        return {
            "is_store": False,
            "has_update": has_update,
            "available": has_update,  # Backwards compatibility with existing checks
            "current_version": cur_ver,
            "latest_version": tag_name,
            "clean_version": latest_clean,
            "release_name": data.get("name", f"Input Locker {tag_name}"),
            "release_notes": raw_body,
            "release_url": direct_download_url or release_url,
            "html_url": release_url,
            "direct_download_url": direct_download_url,
            "highlights": highlights,
            "published_at": data.get("published_at", ""),
        }
    except Exception as exc:
        logger.debug("Update check silently skipped (offline / network error): %s", exc)
        return None


def check_for_updates_async(
    callback: Callable[[Optional[Dict[str, Any]]], None],
    repo_or_url: str = "",
    current_version: Optional[str] = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> threading.Thread:
    """Run check_for_updates asynchronously in a daemon thread and invoke callback with result."""
    def _worker():
        result = check_for_updates(
            repo_or_url=repo_or_url,
            current_version=current_version,
            timeout=timeout,
        )
        try:
            callback(result)
        except Exception as exc:
            logger.debug("Update check callback failed: %s", exc)

    t = threading.Thread(target=_worker, daemon=True, name="UpdateCheckThread")
    t.start()
    return t


def download_file_with_progress(
    target_url: str,
    dest_path: str,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout: float = 60.0,
) -> str:
    """Download a file over HTTPS with automatic redirect resolution and real-time progress.

    Args:
        target_url: The direct download URL.
        dest_path: Local destination file path.
        on_progress: Callback invoked with {"percent": int, "received_bytes": int, "total_bytes": int}.
        cancel_event: Threading event to signal cancellation.
        timeout: Socket read timeout.

    Returns:
        The downloaded file path.
    """
    if not target_url.startswith("https://"):
        raise ValueError("Download URL must use HTTPS scheme")

    req = urllib.request.Request(
        target_url,
        headers={"User-Agent": f"InputLocker/{get_effective_version()}"},
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        if resp.status != 200:
            raise RuntimeError(f"Server returned HTTP {resp.status}")

        total_bytes = int(resp.headers.get("Content-Length", 0))
        received_bytes = 0
        chunk_size = 65536  # 64 KB

        with open(dest_path, "wb") as f:
            while True:
                if cancel_event and cancel_event.is_set():
                    f.close()
                    try:
                        os.remove(dest_path)
                    except OSError:
                        pass
                    raise RuntimeError("Download cancelled by user")

                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                received_bytes += len(chunk)

                if on_progress:
                    pct = min(100, int((received_bytes / total_bytes) * 100)) if total_bytes > 0 else 0
                    on_progress({
                        "percent": pct,
                        "received_bytes": received_bytes,
                        "total_bytes": total_bytes,
                    })

    return dest_path


def download_update_async(
    download_url: str,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    on_complete: Optional[Callable[[str], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> threading.Thread:
    """Asynchronously download update package in background."""
    def _worker():
        try:
            temp_dir = tempfile.gettempdir()
            filename = f"InputLocker-Update-{int(time.time())}.exe"
            dest = os.path.join(temp_dir, filename)

            res_path = download_file_with_progress(
                target_url=download_url,
                dest_path=dest,
                on_progress=on_progress,
                cancel_event=cancel_event,
            )
            if on_complete:
                on_complete(res_path)
        except Exception as exc:
            logger.error("Update download error: %s", exc)
            if on_error:
                on_error(str(exc))

    t = threading.Thread(target=_worker, daemon=True, name="UpdateDownloadThread")
    t.start()
    return t


def install_update_and_restart(file_path: str, delay_s: float = 0.6) -> bool:
    """Launch the installer / update executable detached and exit current process cleanly."""
    if not file_path or not os.path.exists(file_path):
        logger.error("Installer file does not exist: %s", file_path)
        return False

    try:
        if sys.platform == "win32":
            # DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200
            flags = 0x00000008 | 0x00000200
            subprocess.Popen([file_path], creationflags=flags, close_fds=True)
        else:
            subprocess.Popen([file_path], close_fds=True)

        def _quit():
            try:
                import tkinter as tk
                # Try to exit Tk cleanly if running
            except Exception:
                pass
            os._exit(0)

        threading.Timer(delay_s, _quit).start()
        return True
    except Exception as exc:
        logger.error("Failed to launch update installer %s: %s", file_path, exc)
        return False

