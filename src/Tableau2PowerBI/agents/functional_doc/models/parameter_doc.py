"""ParameterDoc — functional documentation for a Tableau parameter."""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class ParameterDoc(BaseModel):
    """Functional documentation for a Tableau parameter."""

    name: str
    purpose: str = ""
    business_impact: str = ""
    usage_context: str = ""

    @field_validator("usage_context", "purpose", "business_impact", mode="before")
    @classmethod
    def coerce_list_to_str(cls, v: object) -> object:
        """LLMs occasionally return a list instead of a plain string; join them."""
        if isinstance(v, list):
            return "; ".join(str(item) for item in v)
        return v
