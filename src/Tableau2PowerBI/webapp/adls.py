"""
adls.py — Azure Data Lake Storage Gen2 upload helper

Supports three auth strategies (set ADLS_AUTH in config):
  managed_identity   → uses the App Service system-assigned identity (recommended on Azure)
  connection_string  → uses ADLS_CONNECTION_STRING (easiest for local testing)
  service_principal  → uses AZURE_TENANT_ID / CLIENT_ID / CLIENT_SECRET
"""

import logging
from base64 import b64decode, b64encode
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import hmac
from io import BytesIO
from urllib.parse import quote

from Tableau2PowerBI.webapp.settings import settings

log = logging.getLogger(__name__)
_DEFAULT_BLOB_API_VERSION = "2023-11-03"


def upload_to_adls(
    file_bytes: bytes,
    filename: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    """
    Upload file_bytes to ADLS under <filesystem>/<upload_path>/<filename>.
    Returns the full abfss:// URI.
    Raises if ADLS is not configured or upload fails.
    """
    if not settings.adls_configured:
        raise ValueError(
            "ADLS_ACCOUNT_NAME is not set. " "Configure it in .env (local) or App Service settings (Azure)."
        )

    if settings.adls_auth == "connection_string":
        return _upload_via_connection_string(file_bytes, filename, progress_callback=progress_callback)

    service_client = _build_service_client()
    remote_path = f"{settings.adls_upload_path}/{filename}"

    fs_client = service_client.get_file_system_client(settings.adls_filesystem)
    file_client = fs_client.get_file_client(remote_path)
    total_bytes = len(file_bytes)
    upload_kwargs = {"overwrite": True}

    if progress_callback is not None:
        progress_callback(0, total_bytes)

        def _progress_hook(current: int, total: int | None) -> None:
            progress_callback(int(current), int(total or total_bytes))

        upload_kwargs["progress_hook"] = _progress_hook

    file_client.upload_data(file_bytes, **upload_kwargs)

    if progress_callback is not None:
        progress_callback(total_bytes, total_bytes)

    uri = f"abfss://{settings.adls_filesystem}" f"@{settings.adls_account_name}.dfs.core.windows.net" f"/{remote_path}"
    log.info(f"ADLS upload OK → {uri}")
    return uri


def _upload_via_connection_string(
    file_bytes: bytes,
    filename: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    """Upload using direct Blob REST calls with the shared key from the connection string."""
    import requests

    conn = _parse_connection_string(settings.adls_connection_string)
    account_name = conn.get("AccountName") or settings.adls_account_name
    account_key = conn.get("AccountKey")
    if not account_name or not account_key:
        raise ValueError("ADLS_CONNECTION_STRING must include AccountName and AccountKey.")

    blob_base = conn.get("BlobEndpoint") or f"https://{account_name}.blob.core.windows.net"
    blob_base = blob_base.rstrip("/")
    remote_path = f"{settings.adls_upload_path}/{filename}".strip("/")
    encoded_path = "/".join(quote(part, safe="") for part in remote_path.split("/"))
    blob_url = f"{blob_base}/{settings.adls_filesystem}/{encoded_path}"
    blob_path = f"/{settings.adls_filesystem}/{remote_path}"

    total_bytes = len(file_bytes)
    if progress_callback is not None:
        progress_callback(0, total_bytes)

    body = _ProgressBytesIO(file_bytes, progress_callback=progress_callback)
    request_time = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    headers = {
        "x-ms-date": request_time,
        "x-ms-version": _DEFAULT_BLOB_API_VERSION,
        "x-ms-blob-type": "BlockBlob",
        "Content-Length": str(total_bytes),
        "Content-Type": "application/octet-stream",
    }
    headers["Authorization"] = _build_shared_key_auth_header(
        account_name=account_name,
        account_key=account_key,
        method="PUT",
        canonicalized_resource=f"/{account_name}{blob_path}",
        headers=headers,
    )

    response = requests.put(blob_url, headers=headers, data=body)
    response.raise_for_status()

    if progress_callback is not None:
        progress_callback(total_bytes, total_bytes)

    uri = (
        f"abfss://{settings.adls_filesystem}"
        f"@{settings.adls_account_name}.dfs.core.windows.net"
        f"/{remote_path}"
    )
    log.info(f"ADLS upload OK → {uri}")
    return uri


def _parse_connection_string(connection_string: str) -> dict[str, str]:
    """Parse a storage connection string into key-value pairs."""
    parts = [segment.strip() for segment in connection_string.split(";") if segment.strip()]
    values: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values[key] = value
    return values


def _build_shared_key_auth_header(
    *,
    account_name: str,
    account_key: str,
    method: str,
    canonicalized_resource: str,
    headers: dict[str, str],
) -> str:
    """Build a Shared Key authorization header for Azure Blob Storage."""
    x_ms_headers = {
        key.lower(): " ".join(value.split())
        for key, value in headers.items()
        if key.lower().startswith("x-ms-")
    }
    canonicalized_headers = "".join(f"{key}:{x_ms_headers[key]}\n" for key in sorted(x_ms_headers))
    content_length = headers.get("Content-Length", "")
    if content_length == "0":
        content_length = ""

    string_to_sign = "\n".join(
        [
            method,
            "",
            "",
            content_length,
            "",
            headers.get("Content-Type", ""),
            "",
            "",
            "",
            "",
            "",
            "",
            canonicalized_headers + canonicalized_resource,
        ]
    )
    signature = b64encode(
        hmac.new(
            b64decode(account_key),
            string_to_sign.encode("utf-8"),
            sha256,
        ).digest()
    ).decode("utf-8")
    return f"SharedKey {account_name}:{signature}"


class _ProgressBytesIO(BytesIO):
    """Bytes buffer that reports read progress while requests streams the body."""

    def __init__(self, data: bytes, progress_callback: Callable[[int, int], None] | None = None) -> None:
        super().__init__(data)
        self._progress_callback = progress_callback
        self._total = len(data)
        self._last_reported = 0

    def read(self, size: int = -1) -> bytes:
        chunk = super().read(size)
        if self._progress_callback is None:
            return chunk
        current = self.tell()
        if current != self._last_reported:
            self._last_reported = current
            self._progress_callback(current, self._total)
        return chunk


def _build_service_client():
    """Build the DataLakeServiceClient based on ADLS_AUTH strategy."""
    from azure.storage.filedatalake import DataLakeServiceClient

    auth = settings.adls_auth
    account = settings.adls_account_name
    url = f"https://{account}.dfs.core.windows.net"

    if auth == "connection_string":
        conn = settings.adls_connection_string
        if not conn:
            raise ValueError("ADLS_AUTH=connection_string but ADLS_CONNECTION_STRING is not set.")
        return DataLakeServiceClient.from_connection_string(conn)

    elif auth == "service_principal":
        from azure.identity import ClientSecretCredential

        if not all([settings.azure_tenant_id, settings.azure_client_id, settings.azure_client_secret]):
            raise ValueError(
                "ADLS_AUTH=service_principal requires " "AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET."
            )
        credential = ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        return DataLakeServiceClient(account_url=url, credential=credential)

    else:  # default: managed_identity
        from azure.identity import ManagedIdentityCredential

        return DataLakeServiceClient(
            account_url=url,
            credential=ManagedIdentityCredential(),
        )
