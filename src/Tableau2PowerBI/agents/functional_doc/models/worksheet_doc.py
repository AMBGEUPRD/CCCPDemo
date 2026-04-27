"""WorksheetDoc — functional documentation for a single Tableau worksheet."""

from __future__ import annotations

from pydantic import BaseModel, Field

from Tableau2PowerBI.agents.functional_doc.models.field_description import FieldDescription


class WorksheetDoc(BaseModel):
    """Functional documentation for a single Tableau worksheet."""

    name: str
    purpose: str = ""
    visualization_type: str = ""
    metrics_shown: list[str] = Field(default_factory=list)
    dimensions_used: list[str] = Field(default_factory=list)
    filters_explained: list[str] = Field(default_factory=list)
    interactivity: str = ""
    calculated_fields_explained: list[FieldDescription] = Field(default_factory=list)
    business_interpretation: str = ""
