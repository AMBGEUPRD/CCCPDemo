"""Agent implementations for the Tableau → Power BI migration pipeline.

Each agent is a self-contained stage that can be run independently or as
part of the full pipeline via ``t2pbi-pipeline`` (see ``Tableau2PowerBI.cli.run_pipeline``).

Stages (in pipeline order):
    1.  :class:`TableauMetadataExtractorAgent` — parse .twb/.twbx into metadata JSON
    1b. :class:`FunctionalDocAgent` — LLM-driven functional documentation of the workbook
    2.  :class:`PBIPProjectSkeletonAgent` — create empty PBIP project scaffold
    3.  :class:`PBIPSemanticModelGeneratorAgent` — LLM-driven semantic model generation
    4.  :class:`TmdlMeasuresGeneratorAgent` — LLM-driven DAX measures generation
    5.  :class:`PbirReportGeneratorAgent` — LLM-driven PBIR report visuals generation
    6.  :class:`PBIPProjectAssemblerAgent` — merge skeleton + generated model into final output
"""

from Tableau2PowerBI.agents.assembler import PBIPProjectAssemblerAgent
from Tableau2PowerBI.agents.dax_measures import TmdlMeasuresGeneratorAgent
from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent
from Tableau2PowerBI.agents.metadata_extractor import TableauMetadataExtractorAgent
from Tableau2PowerBI.agents.powerbi_metadata_extractor import PowerBIMetadataExtractorAgent
from Tableau2PowerBI.agents.report_page_visuals import ReportPageVisualsAgent
from Tableau2PowerBI.agents.report_skeleton import ReportSkeletonAgent
from Tableau2PowerBI.agents.report_visuals import PbirReportGeneratorAgent
from Tableau2PowerBI.agents.semantic_model import PBIPSemanticModelGeneratorAgent
from Tableau2PowerBI.agents.skeleton import PBIPProjectSkeletonAgent
from Tableau2PowerBI.agents.target_technical_doc import TargetTechnicalDocAgent
from Tableau2PowerBI.agents.warnings_reviewer import WarningsReviewerAgent

__all__ = [
    "FunctionalDocAgent",
    "PBIPProjectAssemblerAgent",
    "PBIPProjectSkeletonAgent",
    "PBIPSemanticModelGeneratorAgent",
    "PbirReportGeneratorAgent",
    "PowerBIMetadataExtractorAgent",
    "ReportPageVisualsAgent",
    "ReportSkeletonAgent",
    "TableauMetadataExtractorAgent",
    "TargetTechnicalDocAgent",
    "TmdlMeasuresGeneratorAgent",
    "WarningsReviewerAgent",
]
