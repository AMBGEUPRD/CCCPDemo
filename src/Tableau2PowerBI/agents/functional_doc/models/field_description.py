"""FieldDescription — a named field with a human-readable description."""

from __future__ import annotations

from pydantic import BaseModel


class FieldDescription(BaseModel):
    """A named field with a human-readable description."""

    name: str
    description: str = ""
