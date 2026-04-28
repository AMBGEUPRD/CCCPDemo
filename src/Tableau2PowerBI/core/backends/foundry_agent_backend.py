"""FoundryAgentBackend — Azure AI Foundry Agents API backend.

Each agent's SKILL.md is stored server-side as the agent's instructions in
Azure AI Foundry. Only the user prompt travels per-request, not the system
prompt, which avoids re-sending the full SKILL.md on every call.

Lifecycle:
- initialize(): looks up the agent by name in Foundry; creates it if missing;
  updates its instructions if the local SKILL.md has changed (creating a new
  versioned snapshot in Foundry, visible and rollback-able via the portal).
- call(): creates a thread with the user message, runs the agent to completion,
  retrieves the assistant reply, then deletes the thread. Stateless — no
  conversation history across calls.
- call_async(): delegates to call() via asyncio.to_thread (azure-ai-agents
  uses synchronous HTTP).
- close(): closes the underlying AgentsClient to release HTTP connections.

SDK requirements: azure-ai-agents>=1.1.0, azure-ai-projects>=2.1.0.
The Agents API lives in azure.ai.agents.AgentsClient (standalone client),
not as a property of AIProjectClient as in older SDK versions.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from Tableau2PowerBI.core.backends.llm_response import LLMResponse
from Tableau2PowerBI.core.backends.shared_clients import _make_sync_credential
from Tableau2PowerBI.core.config import AgentSettings


class FoundryAgentBackend:
    """Azure AI Foundry Agents API backend.

    Stores the system prompt (SKILL.md) server-side in Azure AI Foundry so it
    is not re-sent on every LLM call. Requires the Azure AI Developer role
    (``agents/write``) on the AI Services resource.
    """

    def __init__(self) -> None:
        self._agents_client: Any | None = None
        self._agent_id: str = ""
        self._initialized: bool = False
        self._settings: AgentSettings | None = None
        self._logger: logging.Logger = logging.getLogger(__name__)

    # ── lifecycle ────────────────────────────────────────────────────────

    def initialize(
        self,
        settings: AgentSettings,
        model: str,
        skill_text: str,
        agent_name: str,
        logger: logging.Logger,
    ) -> None:
        """Register or update the agent in Azure AI Foundry (idempotent).

        If the agent already exists and its instructions match the local
        SKILL.md, nothing is changed.  If the instructions differ, the agent
        is updated — Foundry creates a new versioned snapshot visible in the
        portal with full rollback support.
        """
        if self._initialized:
            return

        self._settings = settings
        self._logger = logger

        from azure.ai.agents import AgentsClient

        credential = _make_sync_credential(settings.tenant_id)
        agents_client = AgentsClient(endpoint=settings.project_endpoint, credential=credential)
        self._agents_client = agents_client

        existing = self._find_agent_by_name(agents_client, agent_name)
        if existing is not None:
            if existing.instructions != skill_text:
                agents_client.update_agent(existing.id, instructions=skill_text)
                logger.info("Updated Foundry agent instructions name=%s", agent_name)
            self._agent_id = existing.id
        else:
            agent = agents_client.create_agent(
                model=model,
                name=agent_name,
                instructions=skill_text,
            )
            self._agent_id = agent.id
            logger.info("Created Foundry agent name=%s id=%s", agent_name, agent.id)

        self._initialized = True
        logger.debug("FoundryAgentBackend ready agent_id=%s model=%s", self._agent_id, model)

    # ── call ─────────────────────────────────────────────────────────────

    def call(self, prompt: str) -> LLMResponse:
        """Send a prompt to the Foundry agent and return the response.

        Creates a fresh thread for each call (stateless).  The thread is
        deleted after the response is retrieved to avoid accumulation.
        """
        if not self._initialized or self._agents_client is None:
            raise RuntimeError("Backend not initialized. Call initialize() first.")

        from azure.ai.agents.models import AgentThreadCreationOptions, MessageRole, ThreadMessageOptions

        pc = self._agents_client
        started_at = time.monotonic()

        thread_opts = AgentThreadCreationOptions(
            messages=[ThreadMessageOptions(role=MessageRole.USER, content=prompt)]
        )

        run = pc.create_thread_and_process_run(
            agent_id=self._agent_id,
            thread=thread_opts,
        )

        try:
            if run.status != "completed":
                raise RuntimeError(
                    f"Foundry agent run ended with unexpected status '{run.status}'"
                )

            msg = pc.messages.get_last_message_text_by_role(run.thread_id, MessageRole.AGENT)
            if msg is None:
                raise ValueError("Foundry agent returned no assistant message")
            text = msg.text.value
            if not text:
                raise ValueError("Foundry agent returned an empty response")

            usage = getattr(run, "usage", None)
            tokens_in = getattr(usage, "prompt_tokens", 0)
            tokens_out = getattr(usage, "completion_tokens", 0)
            elapsed = time.monotonic() - started_at

            self._logger.debug(
                "call() completed elapsed=%.1fs tokens_in=%d tokens_out=%d",
                elapsed,
                tokens_in,
                tokens_out,
            )
            return LLMResponse(
                text=text,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                elapsed_seconds=elapsed,
            )
        finally:
            # Delete thread to avoid accumulation — each call is independent.
            try:
                pc.threads.delete(run.thread_id)
            except Exception:
                pass

    async def call_async(self, prompt: str) -> LLMResponse:
        """Async wrapper around :meth:`call` via ``asyncio.to_thread``.

        The azure-ai-agents SDK uses synchronous HTTP, so we delegate to the
        thread pool rather than blocking the event loop directly.
        """
        return await asyncio.to_thread(self.call, prompt)

    def close(self) -> None:
        """Close the underlying AgentsClient and release HTTP connections."""
        if self._agents_client is not None:
            try:
                self._agents_client.close()
            except Exception:
                pass

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _find_agent_by_name(client: Any, name: str) -> Any | None:
        """Look up a Foundry agent by name, returning None if not found."""
        try:
            for agent in client.list_agents():
                if agent.name == name:
                    return agent
        except Exception:
            pass
        return None
