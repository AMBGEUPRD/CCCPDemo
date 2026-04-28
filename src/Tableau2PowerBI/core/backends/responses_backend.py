"""ResponsesBackend — OpenAI Responses API backend for Azure AI Foundry."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from Tableau2PowerBI.core.backends.llm_response import LLMResponse
from Tableau2PowerBI.core.backends.shared_clients import shared_client_cache
from Tableau2PowerBI.core.config import AgentSettings


def _create_project_client(settings: AgentSettings) -> Any:
    """Create an Azure AI Projects client using DefaultAzureCredential.

    Locally uses your ``az login`` session; on Azure uses managed identity.
    """
    from Tableau2PowerBI.core.backends.shared_clients import create_project_client

    return create_project_client(settings)


def _create_async_project_client(settings: AgentSettings) -> Any:
    """Create an **async** Azure AI Projects client."""
    from Tableau2PowerBI.core.backends.shared_clients import create_async_project_client

    return create_async_project_client(settings)


class ResponsesBackend:
    """OpenAI Responses API backend (``responses.stream()``).

    Used for OpenAI models deployed in Azure AI Foundry.  The SKILL
    prompt is registered server-side as part of a ``PromptAgentDefinition``
    so it is NOT re-sent on every call — only the user prompt travels
    per-request.
    """

    def __init__(self, use_shared_clients: bool = True) -> None:
        self._project_client: Any | None = None
        self._openai_client: Any | None = None
        self._initialized: bool = False
        self._settings: AgentSettings | None = None
        self._model: str = ""
        self._skill_text: str = ""
        self._agent_name: str = ""
        self._logger: logging.Logger = logging.getLogger(__name__)
        self._use_shared_clients = use_shared_clients
        self._owns_clients = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def initialize(
        self,
        settings: AgentSettings,
        model: str,
        skill_text: str,
        agent_name: str,
        logger: logging.Logger,
    ) -> None:
        """Create project client, openai client, and register the agent."""
        if self._initialized:
            return  # idempotent

        self._settings = settings
        self._model = model
        self._skill_text = skill_text
        self._agent_name = agent_name
        self._logger = logger

        if self._use_shared_clients:
            self._project_client, self._openai_client = shared_client_cache.get_or_create(settings)
            self._owns_clients = False
        else:
            self._project_client = _create_project_client(settings)
            self._openai_client = self._project_client.get_openai_client(
                timeout=settings.request_timeout_seconds,
            )
            self._owns_clients = True

        self._initialized = True
        self._logger.debug("Backend initialized agent_name=%s model=%s", agent_name, model)

    def call(self, prompt: str) -> LLMResponse:
        """Send a prompt via the OpenAI Responses API (non-streaming).

        Uses ``responses.create()`` instead of ``responses.stream()``
        because the openai SDK v2.31.0 streaming parser calls
        ``.to_dict()`` on event objects that Azure AI Foundry returns as
        raw dicts when using ``agent_reference``, causing a systematic
        ``AttributeError`` on every call.  Non-streaming bypasses the
        SDK stream parser entirely and works reliably.
        """
        if self._openai_client is None or not self._initialized:
            raise RuntimeError("Backend not initialized. Call initialize() first.")

        request_kwargs = {
            "model": self._model,
            "input": prompt,
            "instructions": self._skill_text,
            "metadata": {
                "agent_name": self._agent_name,
            },
        }

        started_at = time.monotonic()
        text, tokens_in, tokens_out = self._call_non_streaming(request_kwargs, started_at)
        elapsed = time.monotonic() - started_at
        self._logger.debug("call() completed elapsed=%.1fs chars_out=%d", elapsed, len(text))

        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            elapsed_seconds=elapsed,
        )

    def close(self) -> None:
        """Release SDK clients (only if this instance owns them)."""
        if not self._owns_clients:
            return
        for resource in (self._openai_client, self._project_client):
            close_fn = getattr(resource, "close", None)
            if callable(close_fn):
                close_fn()

    # ── async call ───────────────────────────────────────────────────────

    async def call_async(self, prompt: str) -> LLMResponse:
        """Async version of :meth:`call` using ``AsyncOpenAI``."""
        if not self._initialized or self._settings is None:
            raise RuntimeError("Backend not initialized. Call initialize() first.")

        _, async_openai = await shared_client_cache.get_or_create_async(self._settings)

        request_kwargs = {
            "model": self._model,
            "input": prompt,
            "instructions": self._skill_text,
            "metadata": {
                "agent_name": self._agent_name,
            },
        }

        started_at = time.monotonic()
        response = await async_openai.responses.create(**request_kwargs)
        text = response.output_text or ""
        if not text:
            raise ValueError("Non-streaming response produced no output text")

        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "input_tokens", 0)
        tokens_out = getattr(usage, "output_tokens", 0)
        elapsed = time.monotonic() - started_at
        self._logger.debug("call_async() completed elapsed=%.1fs chars=%d", elapsed, len(text))

        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            elapsed_seconds=elapsed,
        )

    # ── non-streaming fallback ───────────────────────────────────────────

    def _call_non_streaming(
        self,
        request_kwargs: dict[str, Any],
        started_at: float,
    ) -> tuple[str, int, int]:
        """Fallback: call the Responses API without streaming."""
        response = self._openai_client.responses.create(**request_kwargs)
        text = response.output_text or ""
        if not text:
            raise ValueError("Non-streaming response produced no output text")

        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "input_tokens", 0)
        tokens_out = getattr(usage, "output_tokens", 0)
        elapsed = time.monotonic() - started_at
        self._logger.debug("Non-streaming fallback ok elapsed=%.1fs chars=%d", elapsed, len(text))
        return text, tokens_in, tokens_out

    # ── streaming internals ──────────────────────────────────────────────

    def _collect_stream(self, stream: Any, started_at: float) -> tuple[str, int, int]:
        """Consume Responses API stream events, return (text, in, out)."""
        assert self._settings is not None
        parts: list[str] = []
        tokens_in = 0
        tokens_out = 0

        for event in stream:
            elapsed = time.monotonic() - started_at
            if elapsed > self._settings.stream_timeout_seconds:
                raise TimeoutError(f"Stream exceeded timeout after {elapsed:.1f}s")

            event_type = getattr(event, "type", None)

            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "") or ""
                parts.append(delta)

            elif event_type == "response.completed":
                usage = getattr(getattr(event, "response", None), "usage", None)
                tokens_in = getattr(usage, "input_tokens", 0)
                tokens_out = getattr(usage, "output_tokens", 0)
                self._logger.debug(
                    "Stream completed elapsed=%.1fs tokens_out=%d",
                    elapsed,
                    tokens_out,
                )
                break

            elif event_type == "error":
                error = getattr(event, "error", event)
                raise RuntimeError(f"Stream error: {error}")

        text = "".join(parts)
        if not text:
            raise ValueError("Stream produced no output text")

        return text, tokens_in, tokens_out
