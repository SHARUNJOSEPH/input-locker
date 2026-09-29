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

