"""WorkbookSummary — top-level summary of the entire Tableau workbook."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkbookSummary(BaseModel):
    """Top-level summary of the entire Tableau workbook."""

    title: str
    purpose: str
    target_audience: str = ""
    key_business_questions: list[str] = Field(default_factory=list)
