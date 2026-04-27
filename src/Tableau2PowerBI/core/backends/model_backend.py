"""ModelBackend — protocol that all LLM backends must implement."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from Tableau2PowerBI.core.backends.llm_response import LLMResponse
from Tableau2PowerBI.core.config import AgentSettings


@runtime_checkable
class ModelBackend(Protocol):
    """Protocol that all LLM backends must implement.

    The three methods define the full lifecycle of a backend:
    initialize → call (repeatable) → close.
    """

    def initialize(
        self,
        settings: AgentSettings,
        model: str,
        skill_text: str,
        agent_name: str,
        logger: logging.Logger,
    ) -> None:
        """Set up SDK clients and register the agent (if applicable)."""
        ...

    def call(self, prompt: str) -> LLMResponse:
        """Send a prompt to the LLM and return the full response."""
        ...

    async def call_async(self, prompt: str) -> LLMResponse:
        """Async version of call()."""
        ...

    def close(self) -> None:
        """Release SDK clients and their underlying connections."""
        ...
