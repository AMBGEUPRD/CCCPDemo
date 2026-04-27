"""Tests for the webapp launcher entrypoint."""

from __future__ import annotations

from unittest.mock import patch

from Tableau2PowerBI.webapp.__main__ import main


def test_main_uses_loopback_defaults():
    """The dev launcher should default to a browser-safe loopback host."""
    with patch("Tableau2PowerBI.webapp.__main__.uvicorn.run") as run:
        main()

    run.assert_called_once_with(
        "Tableau2PowerBI.webapp.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


def test_main_allows_host_and_port_overrides(monkeypatch):
    """Explicit environment overrides should still be honored."""
    monkeypatch.setenv("WEBAPP_HOST", "0.0.0.0")
    monkeypatch.setenv("WEBAPP_PORT", "9000")
    monkeypatch.setenv("WEBAPP_RELOAD", "true")

    with patch("Tableau2PowerBI.webapp.__main__.uvicorn.run") as run:
        main()

    run.assert_called_once_with(
        "Tableau2PowerBI.webapp.app:app",
        host="0.0.0.0",
        port=9000,
        reload=True,
    )
