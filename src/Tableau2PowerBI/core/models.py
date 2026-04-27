"""Shared Pydantic models used across multiple pipeline agents.

Centralises domain models that would otherwise be duplicated in
individual agent packages.
"""

from __future__ import annotations

from pydantic import BaseModel


class MigrationWarning(BaseModel):
    """A single migration warning emitted by the LLM."""

    severity: str
    code: str
    message: str
    timestamp: str
