"""FunctionalDocumentation — complete functional documentation root model."""

from __future__ import annotations

from pydantic import BaseModel, Field

from Tableau2PowerBI.agents.functional_doc.models.consolidation_profile import ConsolidationProfile
from Tableau2PowerBI.agents.functional_doc.models.cross_cutting_insights import CrossCuttingInsights
from Tableau2PowerBI.agents.functional_doc.models.dashboard_doc import DashboardDoc
from Tableau2PowerBI.agents.functional_doc.models.data_source_doc import DataSourceDoc
from Tableau2PowerBI.agents.functional_doc.models.parameter_doc import ParameterDoc
from Tableau2PowerBI.agents.functional_doc.models.workbook_summary import WorkbookSummary
from Tableau2PowerBI.agents.functional_doc.models.worksheet_doc import WorksheetDoc


class FunctionalDocumentation(BaseModel):
    """Complete functional documentation of a Tableau workbook.

    This is the root model returned by the LLM and validated by Pydantic
    before being passed to the Markdown / HTML renderers.
    """

    workbook_summary: WorkbookSummary
    consolidation_profile: ConsolidationProfile = Field(default_factory=ConsolidationProfile)
    data_sources: list[DataSourceDoc] = Field(default_factory=list)
    dashboards: list[DashboardDoc] = Field(default_factory=list)
    standalone_worksheets: list[WorksheetDoc] = Field(default_factory=list)
    parameters: list[ParameterDoc] = Field(default_factory=list)
    cross_cutting_insights: CrossCuttingInsights = Field(
        default_factory=CrossCuttingInsights,
    )
