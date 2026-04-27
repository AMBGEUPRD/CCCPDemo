"""
config.py — Centralized configuration
All settings are read from environment variables.

LOCAL DEV  → create a .env file in the project root (never commit it)
AZURE      → set the same keys in App Service → Configuration → App Settings
"""

import os
from dataclasses import dataclass, field


def _require(key: str) -> str:
    """Read a required env var; raise a clear error if missing."""
    val = os.environ.get(key, "").strip()
    if not val:
        raise EnvironmentError(
            f"Missing required environment variable: {key}\n"
            f"  → Set it in your .env file (local) or App Service Configuration (Azure)."
        )
    return val


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


# ── Load .env automatically in local dev ──
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — fine in Azure, just use real env vars


@dataclass
class Settings:
    """Environment-backed configuration for the FastAPI webapp."""

    # ──────────────────────────────────────────────
    #  ADLS — Azure Data Lake Storage Gen2
    # ──────────────────────────────────────────────

    # Storage account name  e.g. "mystorageaccount"
    # (without .dfs.core.windows.net)
    adls_account_name: str = field(default_factory=lambda: _optional("ADLS_ACCOUNT_NAME"))

    # Container / filesystem name  e.g. "tableau"
    adls_filesystem: str = field(default_factory=lambda: _optional("ADLS_FILESYSTEM", "tableau"))

    # Folder inside the filesystem  e.g. "uploads"
    adls_upload_path: str = field(default_factory=lambda: _optional("ADLS_UPLOAD_PATH", "uploads"))

    # Auth strategy: "managed_identity" (recommended on Azure)
    #                "connection_string" (for local testing)
    #                "service_principal" (CI/CD or multi-tenant)
    adls_auth: str = field(default_factory=lambda: _optional("ADLS_AUTH", "managed_identity"))

    # Only needed when adls_auth = "connection_string"
    adls_connection_string: str = field(default_factory=lambda: _optional("ADLS_CONNECTION_STRING"))

    # Only needed when adls_auth = "service_principal"
    azure_tenant_id: str = field(default_factory=lambda: _optional("AZURE_TENANT_ID"))
    azure_client_id: str = field(default_factory=lambda: _optional("AZURE_CLIENT_ID"))
    azure_client_secret: str = field(default_factory=lambda: _optional("AZURE_CLIENT_SECRET"))

    # ──────────────────────────────────────────────
    #  App
    # ──────────────────────────────────────────────
    max_file_size_mb: int = field(default_factory=lambda: int(_optional("MAX_FILE_SIZE_MB", "10240")))

    @property
    def max_file_size_bytes(self) -> int:
        """Return the configured upload limit in bytes."""
        return self.max_file_size_mb * 1024 * 1024

    @property
    def adls_configured(self) -> bool:
        """True if ADLS settings are present enough to attempt an upload."""
        return bool(self.adls_account_name)


settings = Settings()
