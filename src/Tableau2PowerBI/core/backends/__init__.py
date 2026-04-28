"""LLM backend implementations and factory.

This package provides pluggable backends for different LLM APIs:

- :class:`FoundryAgentBackend` — Azure AI Foundry Agents API (default)
- :class:`ResponsesBackend` — OpenAI Responses API (kept for reference)
- :class:`MockBackend` — Test doubles for unit tests

Use :func:`create_backend` to instantiate backends by type name.
"""

from Tableau2PowerBI.core.backends.factory import create_backend
from Tableau2PowerBI.core.backends.foundry_agent_backend import FoundryAgentBackend
from Tableau2PowerBI.core.backends.llm_response import LLMResponse
from Tableau2PowerBI.core.backends.mock import MockBackend
from Tableau2PowerBI.core.backends.model_backend import ModelBackend
from Tableau2PowerBI.core.backends.responses_backend import ResponsesBackend
from Tableau2PowerBI.core.backends.shared_clients import shared_client_cache

__all__ = [
    "FoundryAgentBackend",
    "ResponsesBackend",
    "MockBackend",
    "LLMResponse",
    "ModelBackend",
    "create_backend",
    "shared_client_cache",
]
