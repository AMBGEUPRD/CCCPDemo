"""
adls.py — Azure Data Lake Storage Gen2 upload helper

Supports three auth strategies (set ADLS_AUTH in config):
  managed_identity   → uses the App Service system-assigned identity (recommended on Azure)
  connection_string  → uses ADLS_CONNECTION_STRING (easiest for local testing)
  service_principal  → uses AZURE_TENANT_ID / CLIENT_ID / CLIENT_SECRET
"""

import logging

from Tableau2PowerBI.webapp.settings import settings

log = logging.getLogger(__name__)


def upload_to_adls(file_bytes: bytes, filename: str) -> str:
    """
    Upload file_bytes to ADLS under <filesystem>/<upload_path>/<filename>.
    Returns the full abfss:// URI.
    Raises if ADLS is not configured or upload fails.
    """
    if not settings.adls_configured:
        raise ValueError(
            "ADLS_ACCOUNT_NAME is not set. " "Configure it in .env (local) or App Service settings (Azure)."
        )

    service_client = _build_service_client()
    remote_path = f"{settings.adls_upload_path}/{filename}"

    fs_client = service_client.get_file_system_client(settings.adls_filesystem)
    file_client = fs_client.get_file_client(remote_path)
    file_client.upload_data(file_bytes, overwrite=True)

    uri = f"abfss://{settings.adls_filesystem}" f"@{settings.adls_account_name}.dfs.core.windows.net" f"/{remote_path}"
    log.info(f"ADLS upload OK → {uri}")
    return uri


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
