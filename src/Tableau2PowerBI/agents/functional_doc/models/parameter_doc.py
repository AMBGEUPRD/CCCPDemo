"""ParameterDoc — functional documentation for a Tableau parameter."""

from __future__ import annotations

from pydantic import BaseModel


class ParameterDoc(BaseModel):
    """Functional documentation for a Tableau parameter."""

    name: str
    purpose: str = ""
    business_impact: str = ""
    usage_context: str = ""
