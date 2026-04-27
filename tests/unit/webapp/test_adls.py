"""Tests for Tableau2PowerBI.webapp.adls upload helper."""

import types
import unittest
from unittest.mock import MagicMock, patch


class UploadToAdlsTests(unittest.TestCase):
    """Test upload_to_adls behaviour with mocked Azure SDK."""

    def test_upload_raises_when_adls_not_configured(self):
        with patch("Tableau2PowerBI.webapp.adls.settings") as mock_settings:
            mock_settings.adls_configured = False

            from Tableau2PowerBI.webapp.adls import upload_to_adls

            with self.assertRaises(ValueError) as ctx:
                upload_to_adls(b"data", "file.twb")
            self.assertIn("ADLS_ACCOUNT_NAME", str(ctx.exception))

    def test_upload_returns_abfss_uri(self):
        mock_file_client = MagicMock()
        mock_fs_client = MagicMock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        mock_service_client = MagicMock()
        mock_service_client.get_file_system_client.return_value = mock_fs_client

        with (
            patch("Tableau2PowerBI.webapp.adls.settings") as mock_settings,
            patch(
                "Tableau2PowerBI.webapp.adls._build_service_client",
                return_value=mock_service_client,
            ),
        ):
            mock_settings.adls_configured = True
            mock_settings.adls_filesystem = "myfs"
            mock_settings.adls_account_name = "myaccount"
            mock_settings.adls_upload_path = "uploads"

            from Tableau2PowerBI.webapp.adls import upload_to_adls

            uri = upload_to_adls(b"content", "test.twb")

        self.assertTrue(
            uri.startswith("abfss://myfs@myaccount.dfs.core.windows.net/uploads/test.twb"),
        )
        mock_file_client.upload_data.assert_called_once()
        args, kwargs = mock_file_client.upload_data.call_args
        self.assertEqual(args[0], b"content")
        self.assertTrue(kwargs["overwrite"])
        self.assertNotIn("progress_hook", kwargs)

    def test_upload_forwards_progress_hook(self):
        mock_file_client = MagicMock()
        mock_fs_client = MagicMock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        mock_service_client = MagicMock()
        mock_service_client.get_file_system_client.return_value = mock_fs_client
        progress_updates = []

        def progress_callback(current: int, total: int) -> None:
            progress_updates.append((current, total))

        with (
            patch("Tableau2PowerBI.webapp.adls.settings") as mock_settings,
            patch(
                "Tableau2PowerBI.webapp.adls._build_service_client",
                return_value=mock_service_client,
            ),
        ):
            mock_settings.adls_configured = True
            mock_settings.adls_filesystem = "myfs"
            mock_settings.adls_account_name = "myaccount"
            mock_settings.adls_upload_path = "uploads"

            from Tableau2PowerBI.webapp.adls import upload_to_adls

            upload_to_adls(b"abcdef", "test.twb", progress_callback=progress_callback)

        _args, kwargs = mock_file_client.upload_data.call_args
        self.assertIn("progress_hook", kwargs)
        kwargs["progress_hook"](3, 6)
        self.assertEqual(progress_updates[0], (0, 6))
        self.assertEqual(progress_updates[1], (6, 6))
        self.assertEqual(progress_updates[2], (3, 6))

    def test_upload_uses_connection_string_rest_path(self):
        progress_updates = []
        response = MagicMock()
        response.raise_for_status.return_value = None

        def progress_callback(current: int, total: int) -> None:
            progress_updates.append((current, total))

        with (
            patch("Tableau2PowerBI.webapp.adls.settings") as mock_settings,
            patch("requests.put", return_value=response) as mock_put,
        ):
            mock_settings.adls_configured = True
            mock_settings.adls_auth = "connection_string"
            mock_settings.adls_filesystem = "tableau"
            mock_settings.adls_account_name = "acct"
            mock_settings.adls_upload_path = "uploads"
            mock_settings.adls_connection_string = (
                "DefaultEndpointsProtocol=https;"
                "AccountName=acct;"
                "AccountKey=" + "QQ==" + ";"
                "EndpointSuffix=core.windows.net"
            )

            from Tableau2PowerBI.webapp.adls import upload_to_adls

            uri = upload_to_adls(b"abc", "file.zip", progress_callback=progress_callback)

        self.assertEqual(uri, "abfss://tableau@acct.dfs.core.windows.net/uploads/file.zip")
        mock_put.assert_called_once()
        call = mock_put.call_args
        self.assertEqual(call.args[0], "https://acct.blob.core.windows.net/tableau/uploads/file.zip")
        self.assertIn("Authorization", call.kwargs["headers"])
        self.assertEqual(progress_updates[0], (0, 3))
        self.assertEqual(progress_updates[-1], (3, 3))


class BuildServiceClientTests(unittest.TestCase):
    """Test _build_service_client dispatches on adls_auth strategy."""

    @staticmethod
    def _azure_sdk_modules() -> dict[str, object]:
        storage_client = MagicMock()
        azure_module = types.ModuleType("azure")
        azure_storage_module = types.ModuleType("azure.storage")
        azure_filedatalake_module = types.ModuleType("azure.storage.filedatalake")
        azure_filedatalake_module.DataLakeServiceClient = storage_client
        return {
            "azure": azure_module,
            "azure.storage": azure_storage_module,
            "azure.storage.filedatalake": azure_filedatalake_module,
        }

    def test_build_service_client_connection_string(self):
        with patch("Tableau2PowerBI.webapp.adls.settings") as mock_settings:
            mock_settings.adls_auth = "connection_string"
            mock_settings.adls_connection_string = "DefaultEndpointsProtocol=https;AccountName=x"
            mock_settings.adls_account_name = "x"

            with (
                patch.dict("sys.modules", self._azure_sdk_modules()),
                patch("azure.storage.filedatalake.DataLakeServiceClient.from_connection_string") as mock_from_cs,
            ):
                mock_from_cs.return_value = MagicMock()

                from Tableau2PowerBI.webapp.adls import _build_service_client

                _build_service_client()
                mock_from_cs.assert_called_once()

    def test_build_service_client_raises_when_connection_string_missing(self):
        with patch("Tableau2PowerBI.webapp.adls.settings") as mock_settings:
            mock_settings.adls_auth = "connection_string"
            mock_settings.adls_connection_string = ""
            mock_settings.adls_account_name = "x"

            with patch.dict("sys.modules", self._azure_sdk_modules()):
                from Tableau2PowerBI.webapp.adls import _build_service_client

                with self.assertRaises(ValueError) as ctx:
                    _build_service_client()
            self.assertIn("ADLS_CONNECTION_STRING", str(ctx.exception))
