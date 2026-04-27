"""Run the webapp with ``python -m Tableau2PowerBI.webapp`` or ``t2pbi-serve``."""

from __future__ import annotations

import os

import uvicorn


def _env_flag(name: str, default: bool) -> bool:
    """Parse a boolean environment flag."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    """Start the FastAPI development server.

    Defaults to a browser-safe loopback host. Override with ``WEBAPP_HOST``
    and ``WEBAPP_PORT`` when remote access is intentionally required.
    Auto-reload is opt-in via ``WEBAPP_RELOAD=1`` to avoid preview clients
    racing the reloader and landing on Chromium's error page.
    """
    host = os.environ.get("WEBAPP_HOST", "127.0.0.1")
    port = int(os.environ.get("WEBAPP_PORT", "8000"))
    reload_enabled = _env_flag("WEBAPP_RELOAD", False)
    uvicorn.run("Tableau2PowerBI.webapp.app:app", host=host, port=port, reload=reload_enabled)


if __name__ == "__main__":
    main()
