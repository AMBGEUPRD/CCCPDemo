"""Mock LLM backend used by unit tests."""

from __future__ import annotations

import logging

from Tableau2PowerBI.core.backends.llm_response import LLMResponse
from Tableau2PowerBI.core.config import AgentSettings


class MockBackend:
    """Test backend that returns canned responses without network calls.

    Accepts a single response string or a list of strings. When a list is
    provided, each call() pops the next response. When a single string is
    provided, it is returned on every call.
    """

    def __init__(
        self,
        responses: str | list[str] = "mock response",
    ) -> None:
        if isinstance(responses, str):
            self._responses: list[str] = [responses]
            self._repeat: bool = True
        else:
            self._responses = list(responses)
            self._repeat = False

        self.calls: list[str] = []
        self.initialized: bool = False
        self.closed: bool = False
        self.model: str = ""
        self.agent_name: str = ""

    def initialize(
        self,
        settings: AgentSettings,
        model: str,
        skill_text: str,
        agent_name: str,
        logger: logging.Logger,
    ) -> None:
        """No-op initialization that records model metadata for tests."""
        self.initialized = True
        self.model = model
        self.agent_name = agent_name

    def call(self, prompt: str) -> LLMResponse:
        """Return the next canned response."""
        self.calls.append(prompt)

        if self._repeat:
            text = self._responses[0]
        elif self._responses:
            text = self._responses.pop(0)
        else:
            raise RuntimeError("MockBackend exhausted all canned responses")

        return LLMResponse(text=text, elapsed_seconds=0.01)

    async def call_async(self, prompt: str) -> LLMResponse:
        """Async variant with the same behavior as the sync method."""
        return self.call(prompt)

    def close(self) -> None:
        """Mark this backend as closed."""
        self.closed = True
