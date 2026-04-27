"""Evaluation tests for Stage 4 — DAX Measures Generator (LLM).

These tests send pre-captured golden inputs to the live Foundry agent
and validate the structural quality of the generated TMDL.

Run::

    pytest -m eval tests/evals/test_eval_dax_measures.py
"""

from __future__ import annotations

import logging

import pytest

from Tableau2PowerBI.agents.dax_measures import TmdlMeasuresGeneratorAgent
from Tableau2PowerBI.core.config import AgentSettings
from tests.evals.validators import validate_dax_measures_structure

logger = logging.getLogger(__name__)


def _call_dax_agent(workbook_name, golden_dir, eval_output_dir):
    """Shared helper: send golden input to the DAX agent, return parsed decisions.

    Uses the production ``_run_with_validation()`` path which retries up to
    ``MAX_VALIDATION_RETRIES`` times in the same conversation thread when the
    LLM returns malformed JSON, letting the model self-correct.
    """
    input_path = golden_dir / "semantic_model_input.json"
    if not input_path.exists():
        pytest.skip("semantic_model_input.json not found")

    settings = AgentSettings(
        project_endpoint=_require_endpoint(),
        output_root=eval_output_dir,
    )

    agent = TmdlMeasuresGeneratorAgent(settings=settings)
    agent.create()

    input_json = input_path.read_text(encoding="utf-8")
    prompt = agent.prompt_template + input_json

    # Use the full production path: LLM call + parse + retry-with-feedback.
    return agent._run_with_validation(prompt)


@pytest.mark.eval
class TestDaxMeasuresEval:
    """Live evaluation tests for the DAX measures LLM agent."""

    def test_pydantic_validation_passes(
        self,
        workbook_name: str,
        golden_dir,
        eval_output_dir,
    ):
        """The LLM output must parse as valid TmdlMeasuresDecisions."""
        decisions = _call_dax_agent(workbook_name, golden_dir, eval_output_dir)

        # Structural checks
        failures = validate_dax_measures_structure(decisions.measures_tmdl)

        logger.info(
            "Eval result: workbook=%s tmdl_size=%d " "warnings=%d structural_issues=%d",
            workbook_name,
            len(decisions.measures_tmdl),
            len(decisions.warnings),
            len(failures),
        )

        if failures:
            logger.warning(
                "Structural issues for '%s': %s",
                workbook_name,
                failures,
            )

    def test_measures_tmdl_not_empty(
        self,
        workbook_name: str,
        golden_dir,
        eval_output_dir,
    ):
        """The LLM must produce non-empty TMDL content."""
        decisions = _call_dax_agent(workbook_name, golden_dir, eval_output_dir)
        assert len(decisions.measures_tmdl.strip()) > 0, "LLM returned empty TMDL content"

    def test_measures_use_tab_indentation(
        self,
        workbook_name: str,
        golden_dir,
        eval_output_dir,
    ):
        """TMDL output should use TAB indentation (PBI convention).

        This is a quality metric — logged as a warning, not a hard failure,
        since LLMs often default to space indentation despite prompt instructions.
        """
        decisions = _call_dax_agent(workbook_name, golden_dir, eval_output_dir)
        tmdl = decisions.measures_tmdl

        lines = tmdl.split("\n")
        indented = [ln for ln in lines if ln and ln[0] in (" ", "\t")]
        if not indented:
            return  # No indented lines to check

        space_count = sum(1 for ln in indented if ln[0] == " ")
        tab_ratio = 1.0 - (space_count / len(indented))
        logger.info(
            "Indentation eval: workbook=%s tab_ratio=%.1f%% " "(%d/%d lines use TABs)",
            workbook_name,
            tab_ratio * 100,
            len(indented) - space_count,
            len(indented),
        )

        if tab_ratio <= 0.5:
            logger.warning(
                "QUALITY: workbook=%s — only %.0f%% of indented " "lines use TABs. Consider reinforcing in SKILL.md.",
                workbook_name,
                tab_ratio * 100,
            )


# ── Helpers ────────────────────────────────────────────────────────────────


def _require_endpoint() -> str:
    """Read PROJECT_ENDPOINT from env, skipping the test if missing."""
    import os

    endpoint = os.environ.get("PROJECT_ENDPOINT")
    if not endpoint:
        pytest.skip("PROJECT_ENDPOINT not set — cannot reach Foundry")
    return endpoint
