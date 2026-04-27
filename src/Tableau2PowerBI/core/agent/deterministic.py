"""Base class for deterministic (non-LLM) pipeline stages.

Use this class for agents that share settings/logging/skill metadata with
LLM stages but never call a model backend.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from Tableau2PowerBI.core.agent.base import load_skill
from Tableau2PowerBI.core.config import AgentSettings, get_agent_settings


class DeterministicAgent:
    """Shared base class for deterministic pipeline stages.

    Deterministic agents still expose ``skill_name`` and ``skill_text`` for
    consistent logging, output-folder conventions, and UI labeling, but model
    invocation methods are intentionally disabled.
    """

    def __init__(
        self,
        skill_name: str,
        *,
        settings: AgentSettings | None = None,
        skill_loader: Callable[[str], str] = load_skill,
    ) -> None:
        self.skill_name = skill_name
        self.agent_name = f"agent-{skill_name.replace('_', '-')}"
        self.settings = settings or get_agent_settings()
        self.skill_text = skill_loader(skill_name)
        self.logger = logging.getLogger(f"Tableau2PowerBI.{skill_name}")

    def create(self) -> "DeterministicAgent":
        """No-op kept for API compatibility with ``Agent`` callers."""
        return self

    def run(self, prompt: str, **kwargs: Any) -> str:
        """Deterministic stages cannot call LLM backends."""
        _ = (prompt, kwargs)
        raise RuntimeError(f"{type(self).__name__} is deterministic and does not support run().")

    async def run_async(self, prompt: str, **kwargs: Any) -> str:
        """Async counterpart to :meth:`run`, always unsupported."""
        _ = (prompt, kwargs)
        raise RuntimeError(f"{type(self).__name__} is deterministic and does not support run_async().")

    def close(self) -> None:
        """No resources to release for deterministic agents."""

    def __enter__(self) -> "DeterministicAgent":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
