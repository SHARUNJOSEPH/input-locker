"""Zero-dependency, asynchronous audio feedback cues for Input Locker state transitions.

Provides acoustic confirmation for front-of-house (FOH) operators and stage
technicians working in dark control booths or remote AV staging racks.
Uses native Windows multimedia API (winsound / WinMM) with SND_ASYNC to guarantee
strictly zero latency overhead on hook callbacks or network loops.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Attempt to import winsound (standard library on Windows)
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:  # pragma: no cover
    winsound = None  # type: ignore
    HAS_WINSOUND = False


def is_audio_available() -> bool:
    """Returns True if the system supports native audio cues."""
    return HAS_WINSOUND and winsound is not None


def play_cue_async(sound_name: str, fallback_type: int = 0) -> None:
    """Play a Windows system audio cue asynchronously.
    
    Guarantees non-blocking execution via SND_ASYNC. If winsound fails or is
    unavailable (e.g., CI / headless container), it fails silently without raising.
    """
    if not is_audio_available():
        return

    def _play() -> None:
        try:
            # SND_ALIAS: name is a registry sound association
            # SND_ASYNC: return immediately without waiting for playback to finish
            # SND_NODEFAULT: do not play default beep if sound is not found
            flags = winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            winsound.PlaySound(sound_name, flags)
        except Exception:
            try:
                # Fallback to MessageBeep if system alias is not defined
                winsound.MessageBeep(fallback_type)
            except Exception as exc:
                logger.debug("Audio cue playback suppressed or unavailable: %s", exc)

    # Spawn daemon thread for complete thread decoupling if desired,
    # or call directly since SND_ASYNC returns in < 0.1 ms
    threading.Thread(target=_play, daemon=True, name="AudioCue").start()


def play_lock_cue() -> None:
    """Play acoustic confirmation cue for Lock state activation.
    
    Uses 'SystemAsterisk' or standard warning tone (crisp, distinctive tone).
    """
    # 0x00000040 = MB_ICONASTERISK
    play_cue_async("SystemAsterisk", fallback_type=0x40)


def play_unlock_cue() -> None:
    """Play acoustic confirmation cue for Unlock state deactivation.
    
    Uses 'SystemNotification' or standard OK tone (reassuring, gentle tone).
    """
    # 0x00000000 = MB_OK
    play_cue_async("SystemNotification", fallback_type=0x00)
