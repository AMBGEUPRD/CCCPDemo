"""ConsolidationProfile — structured signals for portfolio comparison."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConsolidationProfile(BaseModel):
    """Quick-reference signals used by the compare agent to assess merge feasibility."""

    domain: str = ""
    primary_kpis: list[str] = Field(default_factory=list)
    audience_segments: list[str] = Field(default_factory=list)
    granularity: str = ""
    data_source_names: list[str] = Field(default_factory=list)
