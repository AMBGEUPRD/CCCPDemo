"""Agent implementations for the BI portfolio analysis pipeline.

Stages (in pipeline order):
    1. :class:`TableauMetadataExtractorAgent` — parse .twb/.twbx into metadata JSON
    2. :class:`FunctionalDocAgent` — LLM-driven functional documentation and consolidation profile
    3. :class:`TargetTechnicalDocAgent` — LLM-driven target technical documentation (TDD)

Additional agents used by the webapp:
    :class:`WarningsReviewerAgent` — reviews and explains migration warnings
    :class:`FDDCompareAgent`       — portfolio comparison across multiple FDDs
"""

from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent
from Tableau2PowerBI.agents.metadata_extractor import TableauMetadataExtractorAgent
from Tableau2PowerBI.agents.report_page_visuals import ReportPageVisualsAgent
from Tableau2PowerBI.agents.report_skeleton import ReportSkeletonAgent
from Tableau2PowerBI.agents.target_technical_doc import TargetTechnicalDocAgent
from Tableau2PowerBI.agents.warnings_reviewer import WarningsReviewerAgent

__all__ = [
    "FunctionalDocAgent",
    "ReportPageVisualsAgent",
    "ReportSkeletonAgent",
    "TableauMetadataExtractorAgent",
    "TargetTechnicalDocAgent",
    "WarningsReviewerAgent",
]
