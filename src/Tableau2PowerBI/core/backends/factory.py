"""Backend factory — creates LLM backend instances by type name."""

from __future__ import annotations

from typing import Any

from Tableau2PowerBI.core.backends.foundry_agent_backend import FoundryAgentBackend
from Tableau2PowerBI.core.backends.mock import MockBackend
from Tableau2PowerBI.core.backends.model_backend import ModelBackend
from Tableau2PowerBI.core.backends.responses_backend import ResponsesBackend

_BACKEND_REGISTRY: dict[str, type] = {
    "foundry": FoundryAgentBackend,
    "responses": ResponsesBackend,
    "mock": MockBackend,
}


def create_backend(backend_type: str, **kwargs: Any) -> ModelBackend:
    """Create a backend instance by type name.

    Args:
        backend_type: One of ``"responses"`` or ``"mock"``.
        **kwargs: Passed to the backend constructor (e.g.
            ``responses="..."`` for ``MockBackend``).

    Raises:
        ValueError: If ``backend_type`` is not recognised.
    """
    cls = _BACKEND_REGISTRY.get(backend_type)
    if cls is None:
        raise ValueError(f"Unknown backend type: {backend_type!r}. Available: {sorted(_BACKEND_REGISTRY)}")
    return cls(**kwargs)  # type: ignore[call-arg]
