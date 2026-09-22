"""Persistent JSON configuration for Input Locker.

Complies with enterprise security guidelines (NIST SP 800-63B / OWASP) by
using salted PBKDF2-HMAC-SHA256 password hashing and constant-time digest comparison.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

_CONFIG_PATH = Path(os.environ.get("APPDATA", str(Path.home()))) / "InputLocker" / "config.json"
_PBKDF2_ITERATIONS = 100_000


def get_assets_dir() -> Path:
    """Return the assets directory path, compatible with dev and PyInstaller frozen bundle."""
    import sys
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / "assets"
        if bundled.is_dir():
            return bundled
        return Path(sys._MEIPASS)
    dev_path = Path(__file__).resolve().parent.parent.parent / "assets"
    if dev_path.is_dir():
        return dev_path
    return Path(__file__).resolve().parent.parent / "assets"


def get_config_path() -> Path:
    """Return the path to the active JSON config file."""
    return _CONFIG_PATH


def hash_password(plaintext: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hashes a password with PBKDF2-HMAC-SHA256 using a secure random salt.

    Returns:
        tuple[str, str]: (hex_hash, hex_salt)
    """
    if not plaintext:
        return "", ""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        plaintext.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    )
    return dk.hex(), salt


def verify_password(candidate: str, password_hash: str, password_salt: str) -> bool:
    """Verifies a candidate password against stored hash using constant-time comparison."""
    if not password_hash:
        return candidate == ""
    computed_hash, _ = hash_password(candidate, salt=password_salt)
    return secrets.compare_digest(computed_hash, password_hash)


@dataclass
class LockerConfig:
    password: str = ""
    password_hash: str = ""
    password_salt: str = ""
    wallpaper: str = ""
    alpha: int = 180
    lock_on_launch: bool = True
    check_updates: bool = True
    update_repo: str = ""
    first_run: bool = True
    audio_feedback: bool = False
    lock_hotkey: str = "F11"
    unlock_hotkey: str = "Ctrl+Alt+Shift+U"
    language: str = "auto"

    @property
    def has_password(self) -> bool:
        return bool(self.password or self.password_hash)

    def set_password(self, plaintext: str) -> None:
        """Store password and compute cryptographic salted PBKDF2 hash."""
        self.password = plaintext
        self.password_hash, self.password_salt = hash_password(plaintext)

    def verify(self, candidate: str) -> bool:
        """Verify candidate password against current configuration."""
        if self.password_hash:
            return verify_password(candidate, self.password_hash, self.password_salt)
        return candidate == self.password

    # ------------------------------------------------------------------ #
    @classmethod
    def path(cls) -> Path:
        return _CONFIG_PATH

    @classmethod
    def exists(cls) -> bool:
        return _CONFIG_PATH.exists()

    @classmethod
    def load(cls) -> "LockerConfig":
        if _CONFIG_PATH.exists():
            try:
                data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))

                # Ensure backwards-compatibility: if password exists without hash, hash it
                pw = data.get("password", "")
                h = data.get("password_hash", "")
                s = data.get("password_salt", "")
                if pw and not h:
                    h, s = hash_password(pw)

                instance = cls(
                    password="",  # Security: do not keep plaintext password in memory longer than needed
                    password_hash=h,
                    password_salt=s,
                    wallpaper=data.get("wallpaper", ""),
                    alpha=data.get("alpha", 180),
                    lock_on_launch=data.get("lock_on_launch", True),
                    check_updates=data.get("check_updates", True),
                    update_repo=data.get("update_repo", ""),
                    first_run=data.get("first_run", False),
                    audio_feedback=data.get("audio_feedback", False),
                    lock_hotkey=data.get("lock_hotkey", "F11"),
                    unlock_hotkey=data.get("unlock_hotkey", "Ctrl+Alt+Shift+U"),
                    language=data.get("language", "auto"),
                )
                # If the legacy config contained a plaintext password, immediately resave with hash-only
                if pw:
                    instance.save()
                return instance
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        """Saves configuration to disk, strictly omitting any plaintext password."""
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["password"] = ""  # Security: never write plaintext password to disk
        _CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

