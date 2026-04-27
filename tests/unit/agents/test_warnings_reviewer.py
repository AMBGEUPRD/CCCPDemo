"""Tests for the Warnings Reviewer Agent.

Covers: collect_warnings() file scanning, WarningsReviewerAgent response
parsing, and the no-warnings short-circuit — all without LLM calls.
"""

import json
import unittest

from Tableau2PowerBI.agents.warnings_reviewer import (
    WarningsReviewerAgent,
    collect_warnings,
)
from Tableau2PowerBI.core.backends import MockBackend
from Tableau2PowerBI.core.config import AgentSettings
from tests.support import managed_tempdir

# ── collect_warnings ──────────────────────────────────────────────────────


class TestCollectWarnings(unittest.TestCase):
    """Tests for the standalone ``collect_warnings()`` collector."""

    def test_returns_empty_when_no_output_dirs(self):
        """No agent output dirs → total_warnings == 0."""
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://fake",
                output_root=tmpdir,
            )
            result = collect_warnings("NoSuchWorkbook", settings=settings)
            self.assertEqual(result["total_warnings"], 0)
            self.assertEqual(result["by_agent"], {})

    def test_collects_bare_list_format(self):
        """Warnings stored as a bare JSON list are collected."""
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://fake",
                output_root=tmpdir,
            )
            agent_dir = tmpdir / "pbip_semantic_model_generator_agent" / "TestWorkbook"
            agent_dir.mkdir(parents=True)

            warnings_data = [{"severity": "WARN", "code": "W001", "message": "test warning"}]
            (agent_dir / "migration_warnings.json").write_text(json.dumps(warnings_data), encoding="utf-8")

            result = collect_warnings("TestWorkbook", settings=settings)
            self.assertEqual(result["total_warnings"], 1)
            self.assertIn(
                "pbip_semantic_model_generator_agent",
                result["by_agent"],
            )

    def test_collects_wrapped_dict_format(self):
        """Warnings stored as ``{"warnings": [...]}`` are unwrapped."""
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://fake",
                output_root=tmpdir,
            )
            agent_dir = tmpdir / "tmdl_measures_generator_agent" / "TestWorkbook"
            agent_dir.mkdir(parents=True)

            warnings_data = {
                "warnings": [
                    {"severity": "ERROR", "code": "E001", "message": "bad"},
                    {"severity": "WARN", "code": "W002", "message": "meh"},
                ]
            }
            (agent_dir / "warnings.json").write_text(json.dumps(warnings_data), encoding="utf-8")

            result = collect_warnings("TestWorkbook", settings=settings)
            self.assertEqual(result["total_warnings"], 2)

    def test_ignores_non_warnings_json_files(self):
        """JSON files without 'warnings' in the name are skipped."""
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://fake",
                output_root=tmpdir,
            )
            agent_dir = tmpdir / "pbip_semantic_model_generator_agent" / "TestWorkbook"
            agent_dir.mkdir(parents=True)
            (agent_dir / "other_data.json").write_text('{"foo": "bar"}', encoding="utf-8")

            result = collect_warnings("TestWorkbook", settings=settings)
            self.assertEqual(result["total_warnings"], 0)

    def test_handles_malformed_json_gracefully(self):
        """Malformed warnings files are skipped without raising."""
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://fake",
                output_root=tmpdir,
            )
            agent_dir = tmpdir / "pbir_report_generator_agent" / "TestWorkbook"
            agent_dir.mkdir(parents=True)
            (agent_dir / "warnings.json").write_text("NOT VALID JSON", encoding="utf-8")

            result = collect_warnings("TestWorkbook", settings=settings)
            self.assertEqual(result["total_warnings"], 0)


# ── WarningsReviewerAgent ─────────────────────────────────────────────────


class TestWarningsReviewerAgent(unittest.TestCase):
    """Tests for the LLM-powered reviewer (with MockBackend)."""

    def _make_agent(self, mock_response: str) -> WarningsReviewerAgent:
        """Create a WarningsReviewerAgent with a canned response."""
        settings = AgentSettings(project_endpoint="https://fake")
        backend = MockBackend(responses=mock_response)
        agent = WarningsReviewerAgent(settings=settings)
        agent.backend = backend
        agent._backend_initialized = True
        return agent

    def test_no_warnings_returns_trivially(self):
        """Empty by_agent dict short-circuits without calling LLM."""
        agent = self._make_agent("should not be called")
        result = agent.review_warnings({"workbook_name": "X", "total_warnings": 0, "by_agent": {}})
        self.assertEqual(result["total_fixes"], 0)
        self.assertIn("No migration warnings", result["summary"])

    def test_valid_json_response_parsed(self):
        """A valid JSON response from the LLM is returned as-is."""
        review = {
            "summary": "Found 1 issue",
            "total_fixes": 1,
            "fixes": [{"warning": "W001", "suggestion": "do X"}],
        }
        agent = self._make_agent(json.dumps(review))
        result = agent.review_warnings(
            {
                "workbook_name": "W",
                "total_warnings": 1,
                "by_agent": {"some_agent": [{"severity": "WARN", "code": "W001", "message": "m"}]},
            }
        )
        self.assertEqual(result["total_fixes"], 1)

    def test_markdown_fenced_response_stripped(self):
        """Markdown fences around the JSON are stripped before parsing."""
        review = {"summary": "ok", "total_fixes": 0, "fixes": []}
        fenced = f"```json\n{json.dumps(review)}\n```"
        agent = self._make_agent(fenced)
        result = agent.review_warnings(
            {
                "workbook_name": "W",
                "total_warnings": 1,
                "by_agent": {"a": [{"severity": "WARN", "code": "X", "message": "y"}]},
            }
        )
        self.assertEqual(result["total_fixes"], 0)

    def test_invalid_json_raises_valueerror(self):
        """Non-JSON LLM response raises ValueError."""
        agent = self._make_agent("This is not JSON at all")
        with self.assertRaises(ValueError):
            agent.review_warnings(
                {
                    "workbook_name": "W",
                    "total_warnings": 1,
                    "by_agent": {"a": [{"severity": "WARN", "code": "X", "message": "y"}]},
                }
            )


if __name__ == "__main__":
    unittest.main()
