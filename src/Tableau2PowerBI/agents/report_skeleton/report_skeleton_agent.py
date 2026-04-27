"""ReportSkeletonAgent — Pass 1 of the hybrid PBIR generation pipeline."""

from __future__ import annotations

import json
import logging

from Tableau2PowerBI.agents.report_skeleton.builder import build_skeleton_from_tdd
from Tableau2PowerBI.agents.report_skeleton.report_skeleton import ReportSkeleton
from Tableau2PowerBI.core.agent import DeterministicAgent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.json_response import parse_llm_json_object
from Tableau2PowerBI.core.llm_output_parsing import normalise_warnings

logger = logging.getLogger(__name__)


class ReportSkeletonAgent(DeterministicAgent):
    """Legacy Pass 1 wrapper using deterministic skeleton generation.

    The hybrid pipeline now builds the skeleton deterministically from
    TDD report metadata. This class is kept for compatibility with
    existing imports and tests.
    """

    def __init__(
        self,
        model: str | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        super().__init__(
            skill_name="report_skeleton_agent",
            settings=settings,
        )
        _ = model

    def generate_skeleton(
        self,
        workbook_name: str,
        report_metadata: str,
        schema_text: str,
    ) -> ReportSkeleton:
        """Generate the report skeleton deterministically from TDD metadata.

        Args:
            workbook_name: Name of the Tableau workbook.
            report_metadata: JSON-serialised TDD report design section.
            schema_text: Unused legacy parameter.

        Returns:
            A validated ReportSkeleton with pages, visuals, and warnings.
        """
        _ = (workbook_name, schema_text)
        return build_skeleton_from_tdd(json.loads(report_metadata))


def parse_skeleton_response(response: str) -> ReportSkeleton:
    """Parse and validate the raw LLM response into a ReportSkeleton."""
    raw = parse_llm_json_object(response, logger=logger, enable_recovery=True)

    # Normalise warnings: the LLM may use "_warnings" or "warnings".
    if "_warnings" in raw and "warnings" not in raw:
        raw["warnings"] = raw.pop("_warnings")
    if "warnings" in raw:
        raw["warnings"] = normalise_warnings(raw["warnings"])

    return ReportSkeleton.model_validate(raw)
