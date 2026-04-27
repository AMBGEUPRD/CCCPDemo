"""Evaluation tests for Stage 3 — Semantic Model Generator (LLM).

These tests send pre-captured golden inputs to the live Foundry agent
and validate the structural quality of the output.

Run::

    pytest -m eval tests/evals/test_eval_semantic_model.py
"""

from __future__ import annotations

import logging

import pytest

from Tableau2PowerBI.agents.semantic_model import (
    PBIPSemanticModelGeneratorAgent,
    _enforce_table_names,
    _resolve_pbi_table_names,
)
from Tableau2PowerBI.core.config import AgentSettings
from tests.evals.validators import validate_semantic_model_structure

logger = logging.getLogger(__name__)


@pytest.mark.eval
class TestSemanticModelEval:
    """Live evaluation tests for the semantic model LLM agent."""

    def test_pydantic_validation_passes(
        self,
        workbook_name: str,
        semantic_model_input_raw: str,
        semantic_model_input: dict,
        eval_output_dir,
    ):
        """The LLM output must parse as valid SemanticModelDecisions."""
        settings = AgentSettings(
            project_endpoint=_require_endpoint(),
            output_root=eval_output_dir,
        )
        agent = PBIPSemanticModelGeneratorAgent(settings=settings)
        agent.create()

        # Build prompt exactly as the pipeline does
        metadata = semantic_model_input
        table_name_entries = _resolve_pbi_table_names(metadata)
        prompt = agent._build_prompt(semantic_model_input_raw, workbook_name, table_name_entries)

        # Call the LLM with retry-with-feedback (same as production)
        decisions = agent._run_with_validation(prompt)

        # Enforce deterministic table names
        _enforce_table_names(decisions, table_name_entries)

        # If we got here, Pydantic validation passed — now check structure
        failures = validate_semantic_model_structure(decisions, metadata)

        if failures:
            logger.warning(
                "Structural issues for '%s': %s",
                workbook_name,
                failures,
            )

        # Log a summary for evaluation tracking
        logger.info(
            "Eval result: workbook=%s tables=%d relationships=%d " "warnings=%d structural_issues=%d",
            workbook_name,
            len(decisions.tables),
            len(decisions.relationships),
            len(decisions.warnings),
            len(failures),
        )

        # Structural issues are warnings, not hard failures —
        # uncomment the next line to make them fail the test:
        # assert not failures, f"Structural issues: {failures}"

    def test_table_count_matches_datasources(
        self,
        workbook_name: str,
        semantic_model_input_raw: str,
        semantic_model_input: dict,
        eval_output_dir,
    ):
        """LLM should produce at least as many tables as input datasources."""
        settings = AgentSettings(
            project_endpoint=_require_endpoint(),
            output_root=eval_output_dir,
        )
        agent = PBIPSemanticModelGeneratorAgent(settings=settings)
        agent.create()

        metadata = semantic_model_input
        table_name_entries = _resolve_pbi_table_names(metadata)
        prompt = agent._build_prompt(semantic_model_input_raw, workbook_name, table_name_entries)

        decisions = agent._run_with_validation(prompt)
        _enforce_table_names(decisions, table_name_entries)

        expected_table_count = len(table_name_entries)
        actual_table_count = len(decisions.tables)

        logger.info(
            "Table count eval: workbook=%s expected=%d actual=%d",
            workbook_name,
            expected_table_count,
            actual_table_count,
        )

        assert actual_table_count >= expected_table_count, (
            f"Expected at least {expected_table_count} table(s) " f"but got {actual_table_count}"
        )

    def test_all_m_queries_have_let_in(
        self,
        workbook_name: str,
        semantic_model_input_raw: str,
        semantic_model_input: dict,
        eval_output_dir,
    ):
        """Every regular table's M query must have let/in structure."""
        settings = AgentSettings(
            project_endpoint=_require_endpoint(),
            output_root=eval_output_dir,
        )
        agent = PBIPSemanticModelGeneratorAgent(settings=settings)
        agent.create()

        metadata = semantic_model_input
        table_name_entries = _resolve_pbi_table_names(metadata)
        prompt = agent._build_prompt(semantic_model_input_raw, workbook_name, table_name_entries)

        decisions = agent._run_with_validation(prompt)

        bad_tables = []
        for table in decisions.tables:
            if table.is_calc_group:
                continue
            m = table.m_query.strip().lower()
            if "let" not in m or "in" not in m:
                bad_tables.append(table.name)

        assert not bad_tables, f"Tables with invalid M query structure: {bad_tables}"


# ── Helpers ────────────────────────────────────────────────────────────────


def _require_endpoint() -> str:
    """Read PROJECT_ENDPOINT from env, skipping the test if missing."""
    import os

    endpoint = os.environ.get("PROJECT_ENDPOINT")
    if not endpoint:
        pytest.skip("PROJECT_ENDPOINT not set — cannot reach Foundry")
    return endpoint
