"""WarningDecision — a migration warning emitted by the LLM for manual review."""

from __future__ import annotations

from pydantic import BaseModel


class WarningDecision(BaseModel):
    """A migration warning emitted by the LLM for manual review."""

    code: str  # Warning code (e.g. WARN_SET, WARN_AMBIGUOUS_REL)
    severity: str = "warning"  # "warning" or "error"
    message: str  # Human-readable description of the issue
    source_path: str | None = None  # Optional Tableau source path
    manual_review_required: bool = True  # Whether a human must review this
