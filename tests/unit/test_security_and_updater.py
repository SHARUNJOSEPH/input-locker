import unittest
from unittest.mock import patch, MagicMock
import json

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

    @patch('urllib.request.urlopen')
    def test_check_for_updates_detects_release(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            'tag_name': 'v0.9.0',
            'name': 'Input Locker v0.9.0',
            'html_url': 'https://github.com/input-locker/input-locker/releases/tag/v0.9.0',
            'body': 'Release notes here'
        }).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = check_for_updates(current_version='0.1.0')
        self.assertIsNotNone(res)
        self.assertTrue(res['available'])
        self.assertEqual(res['latest_version'], 'v0.9.0')

    @patch('urllib.request.urlopen')
    def test_check_for_updates_offline_safe(self, mock_urlopen):
        mock_urlopen.side_effect = Exception('Network unreachable')
        res = check_for_updates(current_version='0.1.0')
        self.assertIsNone(res)
