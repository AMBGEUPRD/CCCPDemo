"""DashboardDoc — functional documentation for a Tableau dashboard."""

from __future__ import annotations

from pydantic import BaseModel, Field

from Tableau2PowerBI.agents.functional_doc.models.worksheet_doc import WorksheetDoc


class DashboardDoc(BaseModel):
    """Functional documentation for a Tableau dashboard and its sheets."""

    name: str
    purpose: str = ""
    target_audience: str = ""
    key_insights: list[str] = Field(default_factory=list)
    worksheets: list[WorksheetDoc] = Field(default_factory=list)
