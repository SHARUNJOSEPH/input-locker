"""Tier 4 Application Workload: Live AV Staging & Media Server Production Workflows.

Simulates:
- Resolume Arena & Dataton WATCHOUT media server timeline playback
- Show cue input lockout preventing accidental operator tampering during live performances
- Lighting console / show control OSC/UDP cues
- Digital Audio Workstation (DAW) audio buffer uninterrupted rendering
- Operator panic button local hotkey recovery
"""

import time
import pytest
from tests.harness.input_injector import InputInjector
from tests.harness.client_harness import LockerTCPClient, LockerUDPClient, LockerOSCClient
from tests.harness.focus_harness import CompanionFocusHarness
from tests.conftest import TestController


class TestAVStagingWorkflows:
    """Real-World Production Scenarios: AV media servers, DAWs, and live show cues."""

    def test_resolume_show_cue_lock_scenario(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Simulate a Resolume Arena live playback scenario with show cue lock and accidental input."""
        # 1. Background Resolume window active and running show
        focus_harness.bring_to_foreground()
        focus_harness.clear()
        time.sleep(0.05)
        assert focus_harness.is_active

        # 2. Lighting console sends UDP cue to lock input for opening show sequence
        udp_client = LockerUDPClient(port=test_controller.udp_port)
        resp, _ = udp_client.lock()
        assert resp.get("status") == "ok"
        assert test_controller.is_locked
        time.sleep(0.05)

        # 3. Simulate accidental operator input barrage (dropped notebook on keyboard, frantic mouse clicks)
        focus_harness.clear()
        # Keyboard barrage: 20 random key presses
        for vk in [ord('A'), ord('B'), ord('C'), 0x20, 0x0D, 0x1B, 0x70, 0x71]:
            InputInjector.press_key(vk, duration_s=0.002)
        # Mouse barrage: rapid clicks and movements
        for _ in range(5):
            InputInjector.mouse_click(button="left")
            InputInjector.mouse_click(button="right")
            InputInjector.mouse_move_relative(10, 10)
        time.sleep(0.05)

        # 4. Verify Resolume received EXACTLY ZERO input events
        focus_harness.assert_zero_input_received()
        # Verify Resolume NEVER lost window focus
        focus_harness.assert_zero_focus_disruption()

        # 5. Lighting console sends unlock cue at end of scene
        resp_unlock, _ = udp_client.unlock()
        assert resp_unlock.get("status") == "ok"
        assert not test_controller.is_locked
        time.sleep(0.05)

        # 6. Verify operator control is fully restored to Resolume
        focus_harness.clear()
        InputInjector.press_key(ord('Q'), duration_s=0.01)
        time.sleep(0.05)
        focus_harness.assert_input_received(min_count=1, category="keyboard")

    def test_watchout_timeline_playback_uninterrupted(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Simulate multi-screen WATCHOUT display engine playback during input locker activation."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        # Lock engaged via F11
        InputInjector.press_f11()
        time.sleep(0.05)
        assert test_controller.is_locked

        # Verify zero focus loss on WATCHOUT
        focus_harness.assert_zero_focus_disruption()

        # Unlock engaged via combo
        InputInjector.press_unlock_combo()
        time.sleep(0.05)
        assert not test_controller.is_locked

        # Verify zero focus loss on unlock
        focus_harness.assert_zero_focus_disruption()

    def test_daw_audio_engine_focus_preservation(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Simulate a DAW (ProTools/Ableton) requiring unbroken focus to prevent audio buffer drops."""
        focus_harness.bring_to_foreground()
        focus_harness.clear()

        # Cycle lock 3 times via OSC commands
        osc_client = LockerOSCClient(port=test_controller.udp_port)
        for _ in range(3):
            osc_client.lock()
            time.sleep(0.02)
            assert test_controller.is_locked
            osc_client.unlock()
            time.sleep(0.02)
            assert not test_controller.is_locked

        # Assert no WM_KILLFOCUS or inactive messages reached DAW
        focus_harness.assert_zero_focus_disruption()

    def test_operator_panic_button_recovery(
        self,
        test_controller: TestController,
        focus_harness: CompanionFocusHarness,
    ):
        """Simulate emergency unlock recovery via local hotkey combo when network link is lost."""
        # Engaged via network
        client = LockerTCPClient(port=test_controller.tcp_port)
        client.lock()
        assert test_controller.is_locked

        # Operator presses Ctrl+Alt+Shift+U panic combo
        InputInjector.press_unlock_combo()
        time.sleep(0.05)
        assert not test_controller.is_locked
