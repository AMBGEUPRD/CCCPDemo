"""Warnings Reviewer Agent — post-pipeline warning analysis.

Collects ``warnings.json`` / ``migration_warnings.json`` files written by the
upstream pipeline agents and submits them to an LLM that returns structured
fix suggestions for each warning.

Typical usage (from the web endpoint)::

    from Tableau2PowerBI.agents.warnings_reviewer import WarningsReviewerAgent

    agent = WarningsReviewerAgent()
    agent.create()
    warnings_payload = agent.collect_warnings(workbook_name)
    review = agent.review_warnings(warnings_payload)
"""

from __future__ import annotations

import json
import logging

from Tableau2PowerBI.core.agent import Agent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.prompt_utils import compact_json
from Tableau2PowerBI.core.output_dirs import get_output_dir
from Tableau2PowerBI.core.llm_output_parsing import strip_markdown_fences

logger = logging.getLogger(__name__)

# All agent skill names that can emit warnings files, in pipeline order.
# The collector searches each agent's output directory for any JSON file
# whose name contains "warnings" (case-insensitive).
_WARNING_AGENT_NAMES: list[str] = [
    "tableau_metadata_extractor_agent",
    "pbip_semantic_model_generator_agent",
    "tmdl_measures_generator_agent",
    "pbir_report_generator_agent",
]


def collect_warnings(workbook_name: str, settings: AgentSettings | None = None) -> dict:
    """Scan agent output directories for warnings JSON files.

    Searches each known agent's output directory for any ``.json`` file
    whose filename contains ``warnings`` (case-insensitive).  Merges
    them into a single dict keyed by agent skill name.

    Args:
        workbook_name: The workbook stem used to locate output directories.
        settings: Pipeline settings; uses defaults if ``None``.

    Returns:
        A dict with keys ``workbook_name``, ``total_warnings``, and
        ``by_agent`` (a dict mapping agent skill name → list of warning dicts).
    """
    from Tableau2PowerBI.core.config import get_agent_settings

    runtime_settings = settings or get_agent_settings()
    by_agent: dict[str, list[dict]] = {}

    for agent_name in _WARNING_AGENT_NAMES:
        agent_dir = get_output_dir(agent_name, workbook_name, runtime_settings)
        if not agent_dir.is_dir():
            logger.debug("Output dir missing for %s — skipping", agent_name)
            continue

        # Accept any JSON file with "warnings" in its name.
        warning_files = [f for f in agent_dir.iterdir() if f.suffix.lower() == ".json" and "warnings" in f.stem.lower()]

        if not warning_files:
            logger.debug("No warnings file found in %s", agent_dir)
            continue

        agent_warnings: list[dict] = []
        for wf in warning_files:
            try:
                raw = json.loads(wf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read %s: %s", wf, exc)
                continue

            # Warnings can be stored as a bare list or wrapped in {"warnings": [...]}
            if isinstance(raw, list):
                agent_warnings.extend(raw)
            elif isinstance(raw, dict):
                nested = raw.get("warnings", [])
                if isinstance(nested, list):
                    agent_warnings.extend(nested)
                else:
                    # Flat dict — treat the whole object as one warning entry
                    agent_warnings.append(raw)

        if agent_warnings:
            by_agent[agent_name] = agent_warnings
            logger.info(
                "Collected %d warning(s) from %s",
                len(agent_warnings),
                agent_name,
            )

    total = sum(len(w) for w in by_agent.values())
    logger.info("Total warnings collected: %d across %d agent(s)", total, len(by_agent))

    return {
        "workbook_name": workbook_name,
        "total_warnings": total,
        "by_agent": by_agent,
    }


class WarningsReviewerAgent(Agent):
    """LLM-powered reviewer of migration warnings.

    Accepts a collected-warnings payload (as returned by :func:`collect_warnings`)
    and asks the LLM to explain each warning and suggest concrete fix steps.
    """

    def __init__(self, model: str | None = None, settings: AgentSettings | None = None) -> None:
        super().__init__(
            skill_name="warnings_reviewer_agent",
            model=model,
            settings=settings,
        )

    def review_warnings(self, warnings_payload: dict) -> dict:
        """Submit the warnings payload to the LLM and return structured fix suggestions.

        Args:
            warnings_payload: Output of :func:`collect_warnings`.

        Returns:
            Parsed JSON dict with ``summary``, ``total_fixes``, and ``fixes``.

        Raises:
            ValueError: If the LLM response cannot be parsed as JSON.
        """
        if not warnings_payload.get("by_agent"):
            # No warnings — return a trivial success response without an LLM call.
            return {
                "summary": "No migration warnings were found in the agent outputs.",
                "total_fixes": 0,
                "fixes": [],
            }

        prompt = (
            "Review the following migration warnings collected from the "
            "Tableau→Power BI pipeline agents and return structured fix suggestions.\n\n"
            + compact_json(warnings_payload)
        )

        self.logger.info(
            "Submitting %d warning(s) across %d agent(s) for review",
            warnings_payload.get("total_warnings", 0),
            len(warnings_payload.get("by_agent", {})),
        )

        raw_response = self.run(prompt)

        try:
            clean = strip_markdown_fences(raw_response)
            return json.loads(clean)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Warnings reviewer response is not valid JSON. " f"First 200 chars: {raw_response[:200]!r}"
            ) from exc
