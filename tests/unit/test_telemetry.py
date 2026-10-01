"""Unit tests for anonymous usage telemetry and Aptabase integration."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from input_locker.config import LockerConfig
from input_locker.telemetry import (
    APTABASE_APP_KEY,
    APTABASE_ENDPOINT,
    _send_aptabase_event,
    get_install_source,
    record_startup_telemetry,
)


def test_aptabase_configuration_constants():
    """Verify that Aptabase credentials and endpoints are correctly configured."""
    assert APTABASE_APP_KEY == "A-US-7876388880"
    assert "aptabase.com" in APTABASE_ENDPOINT
    assert APTABASE_ENDPOINT.startswith("https://")


@patch("input_locker.telemetry.is_windows_store")
def test_get_install_source(mock_store):
    """Verify install source correctly maps Store container vs GitHub/standalone."""
    mock_store.return_value = True
    assert get_install_source() == "microsoft_store"

    mock_store.return_value = False
    assert get_install_source() == "github"


@patch("urllib.request.urlopen")
def test_send_aptabase_event_success(mock_urlopen):
    """Verify event payload structure and HTTP headers sent to Aptabase."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    result = _send_aptabase_event("test_event", {"foo": "bar"})
    assert result is True

    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args[0][0]
    assert req.full_url == APTABASE_ENDPOINT
    assert req.headers["App-key"] == APTABASE_APP_KEY
    assert req.headers["Content-type"] == "application/json"

    body = json.loads(req.data.decode("utf-8"))
    assert isinstance(body, list)
    assert len(body) == 1
    event = body[0]
    assert event["eventName"] == "test_event"
    assert event["props"]["foo"] == "bar"
    assert "sessionId" in event
    assert "systemProps" in event
    assert event["systemProps"]["osName"] == "Windows"


@patch("urllib.request.urlopen")
def test_send_aptabase_event_network_failure(mock_urlopen):
    """Verify that network exceptions are handled cleanly without crashing."""
    mock_urlopen.side_effect = Exception("Connection refused / Offline")

    result = _send_aptabase_event("test_event")
    assert result is False


@patch("input_locker.telemetry._send_aptabase_event")
def test_record_startup_telemetry_first_install(mock_send):
    """On first run, both app_installed and app_started events are fired, and install is marked."""
    mock_send.return_value = True

    cfg = LockerConfig()
    cfg.telemetry_enabled = True
    cfg.install_recorded = False

    with patch.object(cfg, "save") as mock_save:
        record_startup_telemetry(cfg, async_mode=False)

        assert mock_send.call_count == 2
        calls = [c[0][0] for c in mock_send.call_args_list]
        assert calls == ["app_installed", "app_started"]
        assert cfg.install_recorded is True
        mock_save.assert_called_once()


@patch("input_locker.telemetry._send_aptabase_event")
def test_record_startup_telemetry_subsequent_runs(mock_send):
    """On subsequent runs, only app_started is fired."""
    mock_send.return_value = True

    cfg = LockerConfig()
    cfg.telemetry_enabled = True
    cfg.install_recorded = True

    record_startup_telemetry(cfg, async_mode=False)

    assert mock_send.call_count == 1
    event_name = mock_send.call_args[0][0]
    assert event_name == "app_started"


@patch("input_locker.telemetry._send_aptabase_event")
def test_record_startup_telemetry_opt_out(mock_send):
    """If user opts out (telemetry_enabled=False), no events should ever be fired."""
    cfg = LockerConfig()
    cfg.telemetry_enabled = False
    cfg.install_recorded = False

    record_startup_telemetry(cfg, async_mode=False)
    assert mock_send.call_count == 0
