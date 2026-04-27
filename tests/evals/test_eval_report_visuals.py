"""Evaluation tests for Stage 5 — PBIR Report Generator (LLM).

These tests send pre-captured golden inputs to the live Foundry agent
and validate the structural quality of the generated report files.

Run::

    pytest -m eval tests/evals/test_eval_report_visuals.py
"""

from __future__ import annotations

import json
import logging

import pytest

from Tableau2PowerBI.agents.report_visuals import (
    PbirReportGeneratorAgent,
)
from Tableau2PowerBI.core.config import AgentSettings
from tests.evals.validators import validate_report_structure

logger = logging.getLogger(__name__)


def _call_report_agent(workbook_name, report_input_raw, eval_output_dir):
    """Shared helper: send golden input to the report agent, return parsed decisions.

    Uses the production ``_run_with_validation()`` path which retries up to
    ``MAX_VALIDATION_RETRIES`` times in the same conversation thread when the
    LLM returns malformed JSON, letting the model self-correct.
    """
    settings = AgentSettings(
        project_endpoint=_require_endpoint(),
        output_root=eval_output_dir,
    )
    agent = PbirReportGeneratorAgent(settings=settings)
    agent.create()

    prompt = agent.prompt_template.replace("{workbook_name}", workbook_name) + report_input_raw

    # Use the full production path: LLM call + parse + retry-with-feedback.
    return agent._run_with_validation(prompt)


def _strip_report_prefix(files: dict[str, str]) -> dict[str, str]:
    """Strip the report folder prefix (e.g. 'Workbook.Report/') from file keys.

    The LLM prefixes file paths with '<WorkbookName>.Report/' but the
    structural checks expect bare relative paths like 'definition/report.json'.
    This mirrors the production _validate_completeness logic.
    """
    if not files:
        return files
    first_key = next(iter(files))
    prefix_end = first_key.find("/")
    prefix = first_key[: prefix_end + 1] if prefix_end != -1 else ""
    if not prefix:
        return files
    return {key[len(prefix) :] if key.startswith(prefix) else key: value for key, value in files.items()}


@pytest.mark.eval
class TestReportVisualsEval:
    """Live evaluation tests for the PBIR report LLM agent."""

    def test_pydantic_validation_passes(
        self,
        workbook_name: str,
        report_input_raw: str,
        eval_output_dir,
    ):
        """The LLM output must parse as valid PbirReportDecisions."""
        decisions = _call_report_agent(workbook_name, report_input_raw, eval_output_dir)

        # Structural checks (strip prefix so validators see bare paths)
        stripped_files = _strip_report_prefix(decisions.files)
        failures = validate_report_structure(stripped_files)

        logger.info(
            "Eval result: workbook=%s files=%d " "warnings=%d structural_issues=%d",
            workbook_name,
            len(decisions.files),
            len(decisions.warnings),
            len(failures),
        )

        if failures:
            logger.warning(
                "Structural issues for '%s': %s",
                workbook_name,
                failures,
            )

    def test_required_files_present(
        self,
        workbook_name: str,
        report_input_raw: str,
        eval_output_dir,
    ):
        """Report output must contain all required PBIR files."""
        decisions = _call_report_agent(workbook_name, report_input_raw, eval_output_dir)

        # Strip report folder prefix (e.g. 'Supermercato.Report/')
        # so we can match against bare relative paths.
        stripped = _strip_report_prefix(decisions.files)
        normalised_keys = {k.replace("\\", "/") for k in stripped}

        required = {
            "definition/report.json",
            "definition/version.json",
        }
        missing = required - normalised_keys

        assert not missing, f"Missing required report files: {missing}"

    def test_json_files_are_valid(
        self,
        workbook_name: str,
        report_input_raw: str,
        eval_output_dir,
    ):
        """All .json files in the report output must be valid JSON."""
        decisions = _call_report_agent(workbook_name, report_input_raw, eval_output_dir)

        invalid_files: list[str] = []
        for path, content in decisions.files.items():
            if path.endswith(".json") and isinstance(content, str):
                try:
                    json.loads(content)
                except json.JSONDecodeError as exc:
                    invalid_files.append(path)
                    # Log first 120 chars + error position for debugging.
                    logger.warning(
                        "Invalid JSON in '%s': %s " "| first 120 chars: %.120r",
                        path,
                        exc,
                        content,
                    )

        assert not invalid_files, (
            f"Invalid JSON in {len(invalid_files)}/{len(decisions.files)} " f"report files: {invalid_files}"
        )


# ── Helpers ────────────────────────────────────────────────────────────────


def _require_endpoint() -> str:
    """Read PROJECT_ENDPOINT from env, skipping the test if missing."""
    import os

    endpoint = os.environ.get("PROJECT_ENDPOINT")
    if not endpoint:
        pytest.skip("PROJECT_ENDPOINT not set — cannot reach Foundry")
    return endpoint
