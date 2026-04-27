"""ParameterDecision — a Power BI What-If parameter."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

# Normalise common LLM pbi_type variants to the canonical set.
_PBI_TYPE_ALIASES: dict[str, str] = {
    "decimal": "Number",
    "float": "Number",
    "real": "Number",
    "integer": "Number",
    "int": "Number",
    "double": "Number",
    "number": "Number",
    "string": "Text",
    "str": "Text",
    "text": "Text",
    "date": "Date",
    "datetime": "DateTime",
    "boolean": "Logical",
    "bool": "Logical",
    "logical": "Logical",
}


class ParameterDecision(BaseModel):
    """A Power BI What-If parameter."""

    name: str  # Display name (never includes Tableau brackets)
    pbi_type: Literal["Text", "Number", "Date", "DateTime", "Logical"]
    default_value: str  # M literal expression (strings include quotes)

    @field_validator("pbi_type", mode="before")
    @classmethod
    def normalise_pbi_type(cls, v: str) -> str:
        """Accept common LLM variants and map to canonical values."""
        if isinstance(v, str):
            return _PBI_TYPE_ALIASES.get(v.lower(), v)
        return v
