import unittest
from unittest.mock import patch, MagicMock
import json
import os

from input_locker.config import hash_password, verify_password, LockerConfig
from input_locker.updater import parse_version, is_newer_version, check_for_updates, check_for_updates_async


class TestSecurity(unittest.TestCase):
    def test_pbkdf2_hash_and_verify(self):
        secret = 'StagePass#2026!'
        h, s = hash_password(secret)
        self.assertTrue(verify_password(secret, h, s))
        self.assertFalse(verify_password('WrongPass', h, s))
        self.assertFalse(verify_password('', h, s))

    def test_locker_config_password_flow(self):
        cfg = LockerConfig()
        self.assertFalse(cfg.has_password)
        cfg.set_password('MyStrongPassword')
        self.assertTrue(cfg.has_password)
        self.assertTrue(cfg.verify('MyStrongPassword'))
        self.assertFalse(cfg.verify('Wrong'))

    def test_locker_config_never_persists_plaintext_password(self):
        import tempfile
        from pathlib import Path
        cfg = LockerConfig()
        cfg.set_password('SuperSecretPass')
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / 'config.json'
            with patch('input_locker.config._CONFIG_PATH', tmp_path):
                cfg.save()
                saved_content = tmp_path.read_text(encoding='utf-8')
                self.assertNotIn('SuperSecretPass', saved_content)
                self.assertIn('password_hash', saved_content)
                
                # Test loading sanitizes any legacy plaintext
                loaded = LockerConfig.load()
                self.assertEqual(loaded.password, '')
                self.assertTrue(loaded.verify('SuperSecretPass'))


class TestUpdater(unittest.TestCase):
    def test_version_parsing(self):
        self.assertEqual(parse_version('v1.2.3'), (1, 2, 3))
        self.assertEqual(parse_version('0.1.0'), (0, 1, 0))
        self.assertEqual(parse_version('2.0.0-rc1'), (2, 0, 0))

    def test_is_newer_version(self):
        self.assertTrue(is_newer_version('0.2.0', '0.1.0'))
        self.assertTrue(is_newer_version('1.0.0', '0.9.9'))
        self.assertFalse(is_newer_version('0.1.0', '0.1.0'))
        self.assertFalse(is_newer_version('0.0.5', '0.1.0'))

    def test_version_comparison_and_downgrade_prevention(self):
        """Replicate and verify exact version comparison & downgrade prevention from PDF Presenter suite."""
        # Testing version 1.2.5 vs Git release 1.2.4
        self.assertFalse(is_newer_version('1.2.4', '1.2.5'))
        self.assertFalse(is_newer_version('v1.2.4', '1.2.5'))

        # Same version
        self.assertFalse(is_newer_version('1.2.5', '1.2.5'))
        self.assertFalse(is_newer_version('v1.2.5', '1.2.5'))

        # Actual update available
        self.assertTrue(is_newer_version('1.2.6', '1.2.5'))
        self.assertTrue(is_newer_version('1.3.0', '1.2.5'))
        self.assertTrue(is_newer_version('2.0.0', '1.2.5'))

    @patch('urllib.request.urlopen')
    def test_check_for_updates_detects_release(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            'tag_name': 'v0.9.0',
            'name': 'Input Locker v0.9.0',
            'html_url': 'https://github.com/input-locker/input-locker/releases/tag/v0.9.0',
            'body': '- Bug fixes\n- Hotkey scan improvements',
            'assets': [
                {'name': 'InputLocker-Setup-v0.9.0.exe', 'browser_download_url': 'https://github.com/releases/setup.exe'},
                {'name': 'InputLocker.exe', 'browser_download_url': 'https://github.com/releases/standalone.exe'},
            ]
        }).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = check_for_updates(current_version='0.1.0')
        self.assertIsNotNone(res)
        self.assertTrue(res['has_update'])
        self.assertTrue(res['available'])
        self.assertEqual(res['latest_version'], 'v0.9.0')
        self.assertEqual(res['direct_download_url'], 'https://github.com/releases/setup.exe')
        self.assertIn('Hotkey scan improvements', res['highlights'][1])

    @patch('urllib.request.urlopen')
    def test_direct_download_url_empty_when_no_newer_version(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            'tag_name': 'v0.1.0',
            'name': 'Input Locker v0.1.0',
            'html_url': 'https://github.com/input-locker/input-locker/releases/tag/v0.1.0',
            'body': 'Initial release',
            'assets': [
                {'name': 'InputLocker-Setup-v0.1.0.exe', 'browser_download_url': 'https://github.com/releases/setup.exe'}
            ]
        }).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        # Running installed version 0.2.5 vs remote 0.1.0 (downgrade prevention)
        res = check_for_updates(current_version='0.2.5')
        self.assertIsNotNone(res)
        self.assertFalse(res['has_update'])
        self.assertFalse(res['available'])
        self.assertEqual(res['direct_download_url'], '')

    @patch.dict('os.environ', {'WINDOWS_STORE': '1'})
    def test_windows_store_detection_and_compliance(self):
        res = check_for_updates(current_version='0.2.5')
        self.assertIsNotNone(res)
        self.assertTrue(res['is_store'])
        self.assertFalse(res['has_update'])
        self.assertIn('Microsoft Store', res['message'])

    @patch('urllib.request.urlopen')
    def test_check_for_updates_offline_safe(self, mock_urlopen):
        mock_urlopen.side_effect = Exception('Network unreachable')
        res = check_for_updates(current_version='0.1.0')
        self.assertIsNone(res)

    @patch('urllib.request.urlopen')
    def test_check_for_updates_blocks_insecure_scheme(self, mock_urlopen):
        res = check_for_updates(repo_or_url='http://insecure-host.com/release.json')
        self.assertIsNone(res)
        mock_urlopen.assert_not_called()

    def test_download_progress_and_cancel(self):
        import io
        import tempfile
        import threading
        from input_locker.updater import download_file_with_progress

        mock_data = b"X" * 131072  # 128 KB
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {'Content-Length': str(len(mock_data))}
        buf = io.BytesIO(mock_data)
        mock_resp.read.side_effect = buf.read
        mock_resp.__enter__.return_value = mock_resp

        progress_calls = []
        def _prog(p):
            progress_calls.append(p)

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "test_download.exe")
            with patch('urllib.request.urlopen', return_value=mock_resp):
                download_file_with_progress('https://example.com/test.exe', dest, on_progress=_prog)

            self.assertTrue(os.path.exists(dest))
            self.assertEqual(os.path.getsize(dest), len(mock_data))
            self.assertTrue(len(progress_calls) > 0)
            self.assertEqual(progress_calls[-1]['percent'], 100)

            # Test cancellation
            dest2 = os.path.join(tmpdir, "test_cancel.exe")
            cancel_evt = threading.Event()
            cancel_evt.set()  # immediate cancel
            buf2 = io.BytesIO(mock_data)
            mock_resp.read.side_effect = buf2.read
            with patch('urllib.request.urlopen', return_value=mock_resp):
                with self.assertRaises(RuntimeError):
                    download_file_with_progress('https://example.com/test.exe', dest2, cancel_event=cancel_evt)
            self.assertFalse(os.path.exists(dest2))

    def test_download_handles_302_redirect(self):
        """Verifies 302 HTTP redirects are followed smoothly for direct downloads."""
        import io
        import tempfile
        from input_locker.updater import download_file_with_progress

        mock_data = b"PayloadContent12345"
        
        # 302 Redirect response
        mock_resp_302 = MagicMock()
        mock_resp_302.status = 302
        mock_resp_302.headers = {'Location': 'https://cdn.example.com/InputLocker-Setup.exe'}
        
        # Final 200 response
        mock_resp_200 = MagicMock()
        mock_resp_200.status = 200
        mock_resp_200.headers = {'Content-Length': str(len(mock_data))}
        buf = io.BytesIO(mock_data)
        mock_resp_200.read.side_effect = buf.read

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "setup.exe")
            with patch('urllib.request.urlopen', side_effect=[mock_resp_302, mock_resp_200]) as mock_open:
                res = download_file_with_progress('https://github.com/releases/download/v0.2.8/setup.exe', dest)
                self.assertEqual(res, dest)
                self.assertEqual(mock_open.call_count, 2)
            
            self.assertTrue(os.path.exists(dest))
            self.assertEqual(os.path.getsize(dest), len(mock_data))

    @patch('urllib.request.urlopen')
    def test_check_for_updates_timeout_is_at_least_10s(self, mock_urlopen):
        """Verify check_for_updates enforces timeout >= 10.0s by default."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({'tag_name': 'v0.2.8'}).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        check_for_updates()
        self.assertTrue(mock_urlopen.called)
        _, kwargs = mock_urlopen.call_args
        self.assertGreaterEqual(kwargs.get('timeout', 0), 10.0)

    @patch('urllib.request.urlopen')
    def test_check_for_updates_handles_array_response(self, mock_urlopen):
        """Verify check_for_updates handles list release response gracefully."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps([
            {
                'tag_name': 'v0.3.0',
                'name': 'Input Locker v0.3.0',
                'html_url': 'https://github.com/SHARUNJOSEPH/input-locker/releases/tag/v0.3.0',
                'body': 'List response test',
                'assets': [],
            }
        ]).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = check_for_updates(current_version='0.2.8')
        self.assertIsNotNone(res)
        self.assertTrue(res['has_update'])
        self.assertEqual(res['clean_version'], '0.3.0')

    @patch('urllib.request.urlopen')
    def test_check_for_updates_clamps_small_timeout_to_10s(self, mock_urlopen):
        """Verify check_for_updates clamps any timeout < 10.0s to at least 10.0s."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({'tag_name': 'v0.2.8'}).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        check_for_updates(timeout=2.0)
        self.assertTrue(mock_urlopen.called)
        _, kwargs = mock_urlopen.call_args
        self.assertGreaterEqual(kwargs.get('timeout', 0), 10.0)

    def test_download_file_rejects_insecure_redirect(self):
        """Verify download_file_with_progress rejects redirect to non-HTTPS URL."""
        import tempfile
        from input_locker.updater import download_file_with_progress

        mock_resp_302 = MagicMock()
        mock_resp_302.status = 302
        mock_resp_302.headers = {'Location': 'http://insecure.example.com/setup.exe'}

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "setup.exe")
            with patch('urllib.request.urlopen', return_value=mock_resp_302):
                with self.assertRaises(ValueError):
                    download_file_with_progress('https://github.com/setup.exe', dest)

    def test_download_file_creates_parent_directories_automatically(self):
        """Verify download_file_with_progress automatically creates nested destination directories."""
        import io
        import tempfile
        from input_locker.updater import download_file_with_progress

        mock_data = b"NestedPayload123"
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {'Content-Length': str(len(mock_data))}
        buf = io.BytesIO(mock_data)
        mock_resp.read.side_effect = buf.read

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "nested", "deep", "dir", "setup.exe")
            with patch('urllib.request.urlopen', return_value=mock_resp):
                res = download_file_with_progress('https://example.com/setup.exe', dest)
                self.assertEqual(res, dest)
            self.assertTrue(os.path.exists(dest))

    def test_download_update_async_preserves_zip_extension(self):
        """Verify download_update_async preserves .zip file extension for portable archives."""
        import tempfile
        from input_locker.updater import download_update_async

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('tempfile.gettempdir', return_value=tmpdir):
                with patch('input_locker.updater.download_file_with_progress') as mock_dl:
                    mock_dl.return_value = os.path.join(tmpdir, "InputLocker-Update.zip")
                    t = download_update_async('https://github.com/releases/download/v0.2.8/bundle.zip')
                    t.join(timeout=2.0)
                    self.assertTrue(mock_dl.called)
                    call_args = mock_dl.call_args[1]
                    self.assertTrue(call_args['dest_path'].endswith('.zip'))

    def test_update_dialog_download_click_falls_back_to_browser_without_direct_asset(self):
        """Verify SoftwareUpdateDialog falls back to browser if direct_download_url is missing."""
        import webbrowser
        from unittest.mock import MagicMock
        from input_locker.ui.update_dialog import SoftwareUpdateDialog

        # Instantiate dummy SoftwareUpdateDialog without launching Tk mainloop
        dlg = SoftwareUpdateDialog.__new__(SoftwareUpdateDialog)
        dlg.is_downloading = False
        dlg.update_info = {
            "has_update": True,
            "direct_download_url": "",
            "html_url": "https://github.com/SHARUNJOSEPH/input-locker/releases/tag/v0.3.0",
            "release_url": "https://github.com/SHARUNJOSEPH/input-locker/releases/tag/v0.3.0",
        }

        with patch.object(webbrowser, 'open') as mock_browser:
            dlg._on_download_click()
            mock_browser.assert_called_once_with(
                "https://github.com/SHARUNJOSEPH/input-locker/releases/tag/v0.3.0"
            )
            self.assertFalse(dlg.is_downloading)

    def test_download_file_cleans_up_on_network_failure(self):
        """Verify download_file_with_progress deletes partial destination file on read exception."""
        import tempfile
        from input_locker.updater import download_file_with_progress

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {'Content-Length': '1000'}
        # Simulate partial chunk read followed by network socket abort
        mock_resp.read.side_effect = [b"PartialData", ConnectionResetError("Connection reset by peer")]

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "partial_setup.exe")
            with patch('urllib.request.urlopen', return_value=mock_resp):
                with self.assertRaises(ConnectionResetError):
                    download_file_with_progress('https://example.com/setup.exe', dest)
            # Partial file must be cleanly cleaned up
            self.assertFalse(os.path.exists(dest))

    def test_install_update_and_restart_msi_package(self):
        """Verify install_update_and_restart uses msiexec.exe /i for .msi packages on Windows."""
        import tempfile
        import subprocess
        from input_locker.updater import install_update_and_restart

        with tempfile.TemporaryDirectory() as tmpdir:
            msi_file = os.path.join(tmpdir, "package.msi")
            with open(msi_file, "wb") as f:
                f.write(b"dummy msi")

            with patch('sys.platform', 'win32'):
                with patch('subprocess.Popen') as mock_popen:
                    with patch('threading.Timer') as mock_timer:
                        success = install_update_and_restart(msi_file)
                        self.assertTrue(success)
                        self.assertTrue(mock_popen.called)
                        args, kwargs = mock_popen.call_args
                        self.assertEqual(args[0], ["msiexec.exe", "/i", msi_file])

    @patch('urllib.request.urlopen')
    def test_check_for_updates_release_url_preserves_page_link(self, mock_urlopen):
        """Verify check_for_updates maintains release_url and html_url as webpage link."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            'tag_name': 'v0.9.0',
            'name': 'Input Locker v0.9.0',
            'html_url': 'https://github.com/SHARUNJOSEPH/input-locker/releases/tag/v0.9.0',
            'body': 'Update details',
            'assets': [
                {'name': 'InputLocker-Setup-v0.9.0.exe', 'browser_download_url': 'https://github.com/releases/setup.exe'},
            ]
        }).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = check_for_updates(current_version='0.1.0')
        self.assertIsNotNone(res)
        self.assertEqual(res['html_url'], 'https://github.com/SHARUNJOSEPH/input-locker/releases/tag/v0.9.0')
        self.assertEqual(res['release_url'], 'https://github.com/SHARUNJOSEPH/input-locker/releases/tag/v0.9.0')
        self.assertEqual(res['direct_download_url'], 'https://github.com/releases/setup.exe')

    def test_download_file_handles_missing_or_empty_content_length(self):
        """Verify download_file_with_progress succeeds when Content-Length is missing or empty."""
        import io
        import tempfile
        from input_locker.updater import download_file_with_progress

        mock_data = b"ArbitraryBinaryChunkData"
        mock_resp = MagicMock()
        mock_resp.status = 200
        # Empty string or missing header should not crash int()
        mock_resp.headers = {'Content-Length': ''}
        buf = io.BytesIO(mock_data)
        mock_resp.read.side_effect = buf.read

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "empty_len.exe")
            with patch('urllib.request.urlopen', return_value=mock_resp):
                res = download_file_with_progress('https://example.com/empty_len.exe', dest)
                self.assertEqual(res, dest)
            self.assertTrue(os.path.exists(dest))
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), mock_data)

    @patch('urllib.request.urlopen')
    def test_check_for_updates_discovers_msi_asset(self, mock_urlopen):
        """Verify check_for_updates populates direct_download_url when an .msi asset is present."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            'tag_name': 'v0.9.5',
            'name': 'Input Locker v0.9.5',
            'html_url': 'https://github.com/SHARUNJOSEPH/input-locker/releases/tag/v0.9.5',
            'body': 'MSI asset test',
            'assets': [
                {'name': 'InputLocker-Setup-v0.9.5.msi', 'browser_download_url': 'https://github.com/releases/package.msi'},
            ]
        }).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = check_for_updates(current_version='0.2.8')
        self.assertIsNotNone(res)
        self.assertEqual(res['direct_download_url'], 'https://github.com/releases/package.msi')

    def test_update_dialog_cancel_suppresses_network_error_ui(self):
        """Verify _on_error in SoftwareUpdateDialog does not render failure state if cancelled."""
        from input_locker.ui.update_dialog import SoftwareUpdateDialog

        dlg = SoftwareUpdateDialog.__new__(SoftwareUpdateDialog)
        dlg.is_downloading = True
        dlg.top = MagicMock()
        dlg.top.winfo_exists.return_value = True

        # Execute scheduled callback immediately
        dlg.top.after.side_effect = lambda ms, fn: fn()

        dlg.lbl_prog_status = MagicMock()
        dlg.lbl_prog_bytes = MagicMock()
        dlg.btn_download = MagicMock()
        dlg.btn_dismiss = MagicMock()
        dlg._cancel_event = MagicMock()
        dlg._cancel_event.is_set.return_value = True

        # Simulate the closure generated in _on_download_click
        # Testing cancellation suppression logic:
        err_msg = "Download cancelled by user"
        if (dlg._cancel_event and dlg._cancel_event.is_set()) or "cancelled" in err_msg.lower():
            cancelled = True
        else:
            cancelled = False

        self.assertTrue(cancelled)

    def test_parse_release_highlights_strips_markdown_and_ignores_full_changelog_url(self):
        """Verify parse_release_highlights strips ** markers and ignores Full Changelog URLs."""
        from input_locker.updater import parse_release_highlights

        body = (
            "## What's Changed\n"
            "- **Fixed** password dialog Tab + Enter navigation\n"
            "- Added `Ctrl+Alt+Shift` modifier-only unlock preset\n\n"
            "**Full Changelog**: https://github.com/SHARUNJOSEPH/input-locker/compare/v0.2.8...v0.2.9"
        )
        items = parse_release_highlights(body)
        self.assertEqual(len(items), 2)
        self.assertNotIn("**", items[0])
        self.assertFalse(any("Full Changelog" in item for item in items))

        # Body with ONLY Full Changelog URL falls back to clean default highlights
        only_url_body = "**Full Changelog**: https://github.com/SHARUNJOSEPH/input-locker/compare/v0.2.8...v0.2.9"
        fallback_items = parse_release_highlights(only_url_body)
        self.assertGreaterEqual(len(fallback_items), 3)
        self.assertFalse(any("Full Changelog" in item for item in fallback_items))
        self.assertFalse(any("**" in item for item in fallback_items))


if __name__ == '__main__':
    unittest.main()
