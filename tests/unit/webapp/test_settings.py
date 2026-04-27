"""Tests for Tableau2PowerBI.webapp.settings.Settings."""

import os
import unittest
from unittest.mock import patch


class SettingsTests(unittest.TestCase):
    """Verify Settings reads env vars and computes adls_configured correctly."""

    def _make_settings(self, env: dict[str, str] | None = None):
        """Import and instantiate Settings with controlled env vars.

        We must import Settings inside each test (not at module level)
        because the class reads env vars at instantiation time.
        """
        with patch.dict(os.environ, env or {}, clear=True):
            from Tableau2PowerBI.webapp.settings import Settings

            return Settings()

    def test_adls_configured_true_when_account_name_set(self):
        settings = self._make_settings({"ADLS_ACCOUNT_NAME": "mystorageaccount"})
        self.assertTrue(settings.adls_configured)

    def test_adls_configured_false_when_account_name_empty(self):
        settings = self._make_settings()
        self.assertFalse(settings.adls_configured)

    def test_defaults(self):
        settings = self._make_settings()
        self.assertEqual(settings.adls_filesystem, "tableau")
        self.assertEqual(settings.adls_upload_path, "uploads")
        self.assertEqual(settings.adls_auth, "managed_identity")
        self.assertEqual(settings.max_file_size_mb, 10240)
        self.assertEqual(settings.max_file_size_bytes, 10240 * 1024 * 1024)

    def test_optional_override(self):
        settings = self._make_settings({"ADLS_FILESYSTEM": "mycontainer"})
        self.assertEqual(settings.adls_filesystem, "mycontainer")

    def test_max_file_size_override_updates_bytes(self):
        settings = self._make_settings({"MAX_FILE_SIZE_MB": "256"})
        self.assertEqual(settings.max_file_size_mb, 256)
        self.assertEqual(settings.max_file_size_bytes, 256 * 1024 * 1024)
