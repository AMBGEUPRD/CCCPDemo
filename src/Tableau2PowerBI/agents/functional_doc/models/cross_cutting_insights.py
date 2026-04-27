"""CrossCuttingInsights — observations that span multiple dashboards / data sources."""

from __future__ import annotations

from pydantic import BaseModel


class CrossCuttingInsights(BaseModel):
    """Observations that span multiple dashboards / data sources."""

    data_lineage_summary: str = ""
    interactivity_patterns: str = ""
    limitations_and_notes: str = ""
