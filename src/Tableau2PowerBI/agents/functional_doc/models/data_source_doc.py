"""DataSourceDoc — functional documentation for one Tableau data source."""

from __future__ import annotations

from pydantic import BaseModel, Field

from Tableau2PowerBI.agents.functional_doc.models.field_description import FieldDescription


class DataSourceDoc(BaseModel):
    """Functional documentation for one Tableau data source."""

    name: str
    purpose: str = ""
    key_fields: list[FieldDescription] = Field(default_factory=list)
    relationships_explained: str = ""
