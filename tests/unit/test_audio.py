"""Unit tests for audio cues and safe fallback execution."""

import unittest.mock as mock
import pytest
from input_locker.core import audio


class TestAudioFeedback:
    """Validate non-blocking audio cues."""

    def test_audio_availability_detection(self):
        # On Windows standard environment, audio should be available
        avail = audio.is_audio_available()
        assert isinstance(avail, bool)

    def test_play_lock_cue_does_not_throw(self):
        """Ensure play_lock_cue executes cleanly without throwing."""
        audio.play_lock_cue()

    def test_play_unlock_cue_does_not_throw(self):
        """Ensure play_unlock_cue executes cleanly without throwing."""
        audio.play_unlock_cue()

    def test_audio_fallback_when_winsound_fails(self):
        """Ensure exceptions inside winsound are caught safely without crashing caller."""
        with mock.patch("input_locker.core.audio.winsound") as mock_ws:
            if mock_ws:
                mock_ws.PlaySound.side_effect = RuntimeError("Audio device busy")
                mock_ws.MessageBeep.side_effect = RuntimeError("Beep unavailable")
                # Must not raise
                audio.play_lock_cue()
                audio.play_unlock_cue()

    def test_controller_triggers_audio(self):
        """Ensure LockerController triggers audio cues when audio_feedback=True."""
        from input_locker.core.controller import LockerController

        mock_hook = mock.MagicMock()
        mock_overlay = mock.MagicMock()
        mock_overlay.show_overlay.return_value = True
        mock_overlay.hide_overlay.return_value = True
        mock_overlay.confine_cursor.return_value = True
        mock_overlay.release_cursor.return_value = True

        with mock.patch("input_locker.core.audio.play_lock_cue") as mock_lock_cue, \
             mock.patch("input_locker.core.audio.play_unlock_cue") as mock_unlock_cue:
            
            ctrl = LockerController(
                hook_manager=mock_hook,
                overlay_manager=mock_overlay,
                auto_prewarm=False,
                auto_register_signals=False,
                audio_feedback=True,
            )
            ctrl.lock()
            assert mock_lock_cue.called is True
            ctrl.unlock()
            assert mock_unlock_cue.called is True
