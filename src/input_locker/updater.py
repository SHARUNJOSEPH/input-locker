"""Automatic version update checker for Input Locker.

Implements non-blocking, offline-safe update discovery via GitHub Releases API
or custom JSON release manifests.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import urllib.request
from typing import Callable, Optional

from input_locker import __version__

logger = logging.getLogger(__name__)

# Default repository to check for releases (can be overridden in config.json)
DEFAULT_UPDATE_REPO = "input-locker/input-locker"
_DEFAULT_TIMEOUT_S = 3.0


def parse_version(ver_str: str) -> tuple[int, ...]:
    """Parse a semantic version string (e.g. 'v0.2.1', '1.0.0') into a numeric tuple."""
    clean = re.sub(r"^[^\d]*", "", ver_str.strip())
    tokens = re.split(r"[.\-+]", clean)
    nums = []
    for t in tokens:
        if t.isdigit():
            nums.append(int(t))
        else:
            break
    return tuple(nums) or (0,)


def is_newer_version(remote_version: str, local_version: str = __version__) -> bool:
    """Compare two version strings; return True if remote is strictly greater than local."""
    r_tuple = parse_version(remote_version)
    l_tuple = parse_version(local_version)
    # Pad to equal length for proper comparison
    max_len = max(len(r_tuple), len(l_tuple))
    r_padded = r_tuple + (0,) * (max_len - len(r_tuple))
    l_padded = l_tuple + (0,) * (max_len - len(l_tuple))
    return r_padded > l_padded


def check_for_updates(
    repo_or_url: str = "",
    current_version: str = __version__,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> Optional[dict]:
    """Query release source for newer version.

    Args:
        repo_or_url: 'owner/repo' for GitHub Releases, or a full URL to a release JSON.
        current_version: Current application version string.
        timeout: Network timeout in seconds (default 3.0).

    Returns:
        Dict with release metadata if a newer version is available, else None.
    """
    repo = repo_or_url.strip() or DEFAULT_UPDATE_REPO
    if repo.startswith("http://") or repo.startswith("https://"):
        endpoint = repo
    else:
        endpoint = f"https://api.github.com/repos/{repo}/releases/latest"

    try:
        req = urllib.request.Request(
            endpoint,
            headers={
                "User-Agent": f"InputLocker/{current_version}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))

        tag_name = data.get("tag_name", "") or data.get("version", "")
        if not tag_name:
            return None

        if is_newer_version(tag_name, current_version):
            return {
                "available": True,
                "latest_version": tag_name,
                "release_name": data.get("name", f"Input Locker {tag_name}"),
                "release_url": data.get("html_url", data.get("url", f"https://github.com/{repo}/releases/latest")),
                "body": (data.get("body", "") or "").strip()[:500],
            }
        return None
    except Exception as exc:
        logger.debug("Update check silently skipped (expected on offline staging machines): %s", exc)
        return None


def check_for_updates_async(
    callback: Callable[[Optional[dict]], None],
    repo_or_url: str = "",
    current_version: str = __version__,
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
