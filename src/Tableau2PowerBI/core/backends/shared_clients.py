"""Shared Azure SDK client factories and cache for model backends."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from Tableau2PowerBI.core.config import AgentSettings


def _make_sync_credential(tenant_id: str) -> Any:
    # AzureCliCredential supports tenant_id for explicit tenant targeting (dev).
    # DefaultAzureCredential is used when no tenant is specified (prod/managed identity).
    if tenant_id:
        from azure.identity import AzureCliCredential
        return AzureCliCredential(tenant_id=tenant_id)
    from azure.identity import DefaultAzureCredential
    return DefaultAzureCredential()


def _make_async_credential(tenant_id: str) -> Any:
    if tenant_id:
        from azure.identity.aio import AzureCliCredential
        return AzureCliCredential(tenant_id=tenant_id)
    from azure.identity.aio import DefaultAzureCredential
    return DefaultAzureCredential()


def create_project_client(settings: AgentSettings) -> Any:
    """Create a sync Azure AI Projects client."""
    from azure.ai.projects import AIProjectClient

    credential = _make_sync_credential(settings.tenant_id)

    return AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=credential,
        allow_preview=True,
    )


def create_async_project_client(settings: AgentSettings) -> Any:
    """Create an async Azure AI Projects client."""
    from azure.ai.projects.aio import AIProjectClient

    credential = _make_async_credential(settings.tenant_id)

    return AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=credential,
        allow_preview=True,
    )


class ClientCache:
    """Thread-safe cache for Azure SDK clients, keyed by project endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[Any, Any]] = {}

    def get_or_create(self, settings: AgentSettings) -> tuple[Any, Any]:
        """Return ``(project_client, openai_client)`` for an endpoint."""
        key = settings.project_endpoint
        with self._lock:
            if key not in self._entries:
                project_client = create_project_client(settings)
                openai_client = project_client.get_openai_client(
                    timeout=settings.request_timeout_seconds,
                )
                self._entries[key] = (project_client, openai_client)
            return self._entries[key]

    async def get_or_create_async(self, settings: AgentSettings) -> tuple[Any, Any]:
        """Return ``(async_project_client, async_openai_client)`` for an endpoint."""
        key = f"async:{settings.project_endpoint}"
        with self._lock:
            if key not in self._entries:
                async_project = create_async_project_client(settings)
                async_openai = async_project.get_openai_client(
                    timeout=settings.request_timeout_seconds,
                )
                self._entries[key] = (async_project, async_openai)
            return self._entries[key]

    def close_all(self) -> None:
        """Close all cached sync clients."""
        with self._lock:
            for project_client, openai_client in self._entries.values():
                for client in (openai_client, project_client):
                    close_fn = getattr(client, "close", None)
                    if callable(close_fn):
                        close_fn()
            self._entries.clear()

    async def close_all_async(self) -> None:
        """Close all cached async clients."""
        with self._lock:
            async_keys = [k for k in self._entries if k.startswith("async:")]
            for key in async_keys:
                project_client, openai_client = self._entries.pop(key)
                for client in (openai_client, project_client):
                    close_fn = getattr(client, "close", None)
                    if callable(close_fn):
                        result = close_fn()
                        if asyncio.iscoroutine(result):
                            await result


shared_client_cache = ClientCache()
