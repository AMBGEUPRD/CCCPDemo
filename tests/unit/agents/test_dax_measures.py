"""Tests for the TMDL measures (DAX) generator agent.

Covers: Pydantic model validation, response parsing, TMDL normalisation,
and save behaviour — all without LLM calls.
"""

import json
import logging
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from Tableau2PowerBI.agents.dax_measures import (
    TmdlMeasuresDecisions,
    TmdlMeasuresGeneratorAgent,
    parse_decisions_response,
)
from Tableau2PowerBI.core.models import MigrationWarning

# ── Pydantic models ──────────────────────────────────────────────────────


class TmdlMeasuresDecisionsModelTests(unittest.TestCase):
    def test_valid_minimal(self):
        d = TmdlMeasuresDecisions(measures_tmdl="table Orders\n")
        self.assertEqual(d.measures_tmdl, "table Orders\n")
        self.assertEqual(d.warnings, [])

    def test_empty_tmdl_rejected(self):
        with self.assertRaises(ValidationError):
            TmdlMeasuresDecisions(measures_tmdl="")

    def test_warnings_default_to_empty(self):
        d = TmdlMeasuresDecisions(measures_tmdl="x")
        self.assertEqual(d.warnings, [])

    def test_valid_with_warnings(self):
        d = TmdlMeasuresDecisions(
            measures_tmdl="content",
            warnings=[
                MigrationWarning(
                    severity="WARN",
                    code="W1",
                    message="test",
                    timestamp="2026-01-01T00:00:00Z",
                ),
            ],
        )
        self.assertEqual(len(d.warnings), 1)
        self.assertEqual(d.warnings[0].code, "W1")


# ── _parse_response ──────────────────────────────────────────────────────


class ParseResponseTests(unittest.TestCase):
    def test_clean_json(self):
        raw = json.dumps({"measures.tmdl": "table T\n", "_warnings": []})
        result = parse_decisions_response(raw)
        self.assertEqual(result.measures_tmdl, "table T\n")
        self.assertEqual(result.warnings, [])

    def test_stripped_fences(self):
        raw = "```json\n" + json.dumps({"measures.tmdl": "content"}) + "\n```"
        result = parse_decisions_response(raw)
        self.assertEqual(result.measures_tmdl, "content")

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            parse_decisions_response("not json")

    def test_non_object_raises(self):
        with self.assertRaises(ValueError):
            parse_decisions_response("[1, 2, 3]")

    def test_empty_tmdl_raises(self):
        raw = json.dumps({"measures.tmdl": ""})
        with self.assertRaises((ValueError, ValidationError)):
            parse_decisions_response(raw)

    def test_warnings_normalised_from_strings(self):
        raw = json.dumps(
            {
                "measures.tmdl": "content",
                "_warnings": ["cannot translate TABLE_CALC"],
            }
        )
        result = parse_decisions_response(raw)
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.warnings[0].code, "UNSTRUCTURED_WARNING")
        self.assertEqual(result.warnings[0].message, "cannot translate TABLE_CALC")

    def test_warnings_normalised_from_dicts(self):
        raw = json.dumps(
            {
                "measures.tmdl": "content",
                "_warnings": [
                    {"severity": "error", "code": "E1", "message": "bad calc"},
                ],
            }
        )
        result = parse_decisions_response(raw)
        self.assertEqual(result.warnings[0].severity, "ERROR")
        self.assertEqual(result.warnings[0].code, "E1")


# ── _normalise_tmdl ──────────────────────────────────────────────────────


class NormaliseTmdlTests(unittest.TestCase):
    def test_string_passthrough(self):
        self.assertEqual(
            TmdlMeasuresGeneratorAgent._normalise_tmdl("table T\n"),
            "table T\n",
        )

    def test_list_of_strings_joined_with_crlf(self):
        result = TmdlMeasuresGeneratorAgent._normalise_tmdl(["line one", "line two"])
        self.assertEqual(result, "line one\r\nline two")

    def test_list_of_dicts_uses_line_key(self):
        result = TmdlMeasuresGeneratorAgent._normalise_tmdl([{"line": "table T"}, {"line": "  col C"}])
        self.assertEqual(result, "table T\r\n  col C")

    def test_list_of_dicts_uses_content_key(self):
        result = TmdlMeasuresGeneratorAgent._normalise_tmdl([{"content": "body text"}])
        self.assertEqual(result, "body text")

    def test_list_of_dicts_fallback_to_json(self):
        result = TmdlMeasuresGeneratorAgent._normalise_tmdl([{"unexpected": "shape"}])
        self.assertIn("unexpected", result)

    def test_non_string_non_list_returns_json(self):
        result = TmdlMeasuresGeneratorAgent._normalise_tmdl(42)
        self.assertEqual(result, "42")


# ── Retry-with-feedback ─────────────────────────────────────────────────


def _build_dax_agent():
    """Construct a TmdlMeasuresGeneratorAgent without Azure dependencies."""
    from Tableau2PowerBI.core.config import AgentSettings

    agent = object.__new__(TmdlMeasuresGeneratorAgent)
    agent.skill_name = "tmdl_measures_generator_agent"
    agent.settings = AgentSettings(project_endpoint="https://example.test")
    agent.logger = logging.getLogger("test.dax_measures")
    return agent


class BuildPromptTests(unittest.TestCase):
    def test_no_tables_returns_template_plus_tdd(self):
        agent = _build_dax_agent()
        agent.prompt_template = "TEMPLATE\n\n"
        tdd_dax = {"measures": [{"caption": "Sales", "owner_table": "T"}]}
        result = agent._build_prompt(tdd_dax, {})
        self.assertIn("TEMPLATE", result)
        self.assertIn("Target Technical Design", result)
        self.assertIn('"Sales"', result)

    def test_table_names_prepended_as_mandatory_header(self):
        agent = _build_dax_agent()
        agent.prompt_template = "TEMPLATE\n\n"
        tdd_dax = {"measures": []}
        tdd_sm = {"tables": [{"name": "Orders"}, {"name": "Returns"}]}
        result = agent._build_prompt(tdd_dax, tdd_sm)
        self.assertIn("## Available Power BI Tables (MANDATORY)", result)
        self.assertIn("  - Orders", result)
        self.assertIn("  - Returns", result)
        self.assertIn("TEMPLATE", result)
        # Header must come before the template
        self.assertLess(result.index("Available Power BI"), result.index("TEMPLATE"))


class RetryPreservesOriginalPromptTests(unittest.TestCase):
    """Verify that _run_with_validation includes the original prompt on retries."""

    def test_retry_includes_original_prompt(self):
        agent = _build_dax_agent()
        valid_response = json.dumps({"measures.tmdl": "table T\n", "_warnings": []})
        captured_prompts: list[str] = []

        def mock_run(prompt: str, force_new_conversation: bool = False) -> str:
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                # First call: return invalid JSON to trigger a retry.
                return "not valid json at all"
            # Second call: return valid response.
            return valid_response

        with patch.object(agent, "run", side_effect=mock_run):
            agent._run_with_validation("Original DAX prompt content")

        self.assertEqual(len(captured_prompts), 2)
        # First call should be the original prompt unchanged.
        self.assertEqual(captured_prompts[0], "Original DAX prompt content")
        # Second call must contain BOTH the original prompt and the error feedback.
        self.assertIn("Original DAX prompt content", captured_prompts[1])
        self.assertIn("previous response failed validation", captured_prompts[1])
