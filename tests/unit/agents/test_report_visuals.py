"""Tests for the PBIR report (visuals) generator agent.

Covers: Pydantic model validation, response parsing, content normalisation,
completeness validation, and save behaviour — all without LLM calls.
"""

import json
import logging
import unittest

from pydantic import ValidationError

from Tableau2PowerBI.agents.report_visuals import (
    PbirReportDecisions,
    PbirReportGeneratorAgent,
    parse_decisions_response,
)
from Tableau2PowerBI.agents.report_visuals.output_io import (
    save_decisions,
    validate_completeness,
)
from Tableau2PowerBI.agents.report_visuals.parsing import normalise_content
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.models import MigrationWarning
from Tableau2PowerBI.core.llm_output_parsing import recover_malformed_json
from tests.support import managed_tempdir

# ── Helpers ───────────────────────────────────────────────────────────────


def _complete_report_response(workbook: str = "Test") -> dict:
    """Build a minimal but complete PBIR response dict."""
    prefix = f"{workbook}.Report"
    return {
        f"{prefix}/.platform": '{"metadata": {}}',
        f"{prefix}/definition.pbir": '{"version": "4.0"}',
        f"{prefix}/.pbi/localSettings.json": "{}",
        f"{prefix}/definition/report.json": "{}",
        f"{prefix}/definition/version.json": '{"version": "2.0.0"}',
        f"{prefix}/definition/pages/pages.json": '{"pageOrder":["page1"],"activePageName":"page1"}',
        f"{prefix}/definition/pages/page1/page.json": "{}",
        f"{prefix}/definition/pages/page1/visuals/v1/visual.json": "{}",
    }


def _build_agent():
    """Construct a PbirReportGeneratorAgent without Azure dependencies."""
    agent = object.__new__(PbirReportGeneratorAgent)
    agent.skill_name = "pbir_report_generator_agent"
    agent.settings = AgentSettings(project_endpoint="https://example.test")
    agent.logger = logging.getLogger("test.pbir_visuals")
    return agent


# ── Pydantic models ──────────────────────────────────────────────────────


class PbirReportDecisionsModelTests(unittest.TestCase):
    def test_valid_minimal(self):
        d = PbirReportDecisions(files={"a.json": "content"})
        self.assertEqual(len(d.files), 1)
        self.assertEqual(d.warnings, [])

    def test_empty_files_rejected(self):
        with self.assertRaises(ValidationError):
            PbirReportDecisions(files={})

    def test_warnings_default_to_empty(self):
        d = PbirReportDecisions(files={"f": "c"})
        self.assertEqual(d.warnings, [])

    def test_valid_with_warnings(self):
        d = PbirReportDecisions(
            files={"f": "c"},
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


# ── _parse_response ──────────────────────────────────────────────────────


class ParseResponseTests(unittest.TestCase):
    def test_clean_json(self):
        raw = json.dumps(_complete_report_response())
        result = parse_decisions_response(raw)
        self.assertGreater(len(result.files), 0)
        self.assertEqual(result.warnings, [])

    def test_stripped_fences(self):
        raw = "```json\n" + json.dumps({"file.json": "content"}) + "\n```"
        result = parse_decisions_response(raw)
        self.assertIn("file.json", result.files)

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            parse_decisions_response("not json")

    def test_non_object_raises(self):
        with self.assertRaises(ValueError):
            parse_decisions_response("[1, 2, 3]")

    def test_only_warnings_key_raises(self):
        """A response with only _warnings and no file keys should fail."""
        raw = json.dumps({"_warnings": []})
        with self.assertRaises((ValueError, ValidationError)):
            parse_decisions_response(raw)

    def test_warnings_not_in_files(self):
        """_warnings key should be separated from files, not treated as a file."""
        raw = json.dumps(
            {
                "report/file.json": "content",
                "_warnings": [{"severity": "warn", "code": "W1", "message": "m"}],
            }
        )
        result = parse_decisions_response(raw)
        self.assertNotIn("_warnings", result.files)
        self.assertEqual(len(result.warnings), 1)

    def test_dict_values_serialised_to_json_string(self):
        raw = json.dumps(
            {
                "report/config.json": {"key": "value"},
            }
        )
        result = parse_decisions_response(raw)
        content = result.files["report/config.json"]
        self.assertEqual(json.loads(content), {"key": "value"})


# ── _normalise_content ───────────────────────────────────────────────────


class NormaliseContentTests(unittest.TestCase):
    def test_string_passthrough(self):
        self.assertEqual(
            normalise_content("text"),
            "text",
        )

    def test_dict_serialised(self):
        result = normalise_content({"k": "v"})
        self.assertEqual(json.loads(result), {"k": "v"})

    def test_list_serialised(self):
        result = normalise_content([1, 2])
        self.assertEqual(json.loads(result), [1, 2])

    def test_number_coerced(self):
        result = normalise_content(42)
        self.assertEqual(result, "42")

    def test_json_string_reserialized(self):
        """A JSON string containing a dict/list gets parsed and re-serialised."""
        result = normalise_content('{"k":"v"}')
        parsed = json.loads(result)
        self.assertEqual(parsed, {"k": "v"})
        # Re-serialised with indent=2
        self.assertIn("\n", result)

    def test_non_json_string_passthrough(self):
        """A non-JSON string is returned as-is."""
        self.assertEqual(
            normalise_content("plain text"),
            "plain text",
        )

    def test_truncated_json_recovered(self):
        """A truncated JSON object (missing closing brace) is recovered and re-serialised."""
        # Simulate a token-limit cut-off: valid JSON minus the final '}'
        full = json.dumps({"visualType": "multiRowCard", "query": {"queryState": {}}})
        truncated = full[:-1]  # remove closing '}'
        result = normalise_content(truncated)
        parsed = json.loads(result)
        self.assertEqual(parsed["visualType"], "multiRowCard")


# ── validate_completeness ────────────────────────────────────────────────


class ValidateCompletenessTests(unittest.TestCase):
    def test_complete_response_no_warnings(self):
        agent = _build_agent()
        decisions = PbirReportDecisions(
            files=_complete_report_response("Test"),
        )
        # Should not raise; captures log output to verify no warnings
        with self.assertLogs("test.pbir_visuals", level="INFO") as captured:
            validate_completeness(decisions.files, "Test", agent.logger)
        # No WARNING-level messages expected
        warnings = [m for m in captured.output if "WARNING" in m]
        self.assertEqual(warnings, [])

    def test_missing_required_file_logged(self):
        agent = _build_agent()
        files = _complete_report_response("Test")
        del files["Test.Report/definition/report.json"]
        decisions = PbirReportDecisions(files=files)

        with self.assertLogs("test.pbir_visuals", level="WARNING") as captured:
            validate_completeness(decisions.files, "Test", agent.logger)

        self.assertTrue(
            any("report.json" in m for m in captured.output),
        )

    def test_no_pages_logged(self):
        agent = _build_agent()
        files = {
            "R.Report/.platform": "{}",
            "R.Report/definition.pbir": "{}",
            "R.Report/.pbi/localSettings.json": "{}",
            "R.Report/definition/report.json": "{}",
            "R.Report/definition/version.json": "{}",
        }
        decisions = PbirReportDecisions(files=files)

        with self.assertLogs("test.pbir_visuals", level="WARNING") as captured:
            validate_completeness(decisions.files, "WB", agent.logger)

        self.assertTrue(any("No pages" in m for m in captured.output))

    def test_no_visuals_logged(self):
        agent = _build_agent()
        files = _complete_report_response("Test")
        # Remove the visual file, keep the page
        files = {k: v for k, v in files.items() if "/visuals/" not in k}
        decisions = PbirReportDecisions(files=files)

        with self.assertLogs("test.pbir_visuals", level="WARNING") as captured:
            validate_completeness(decisions.files, "WB", agent.logger)

        self.assertTrue(any("No visuals" in m for m in captured.output))


# ── save_decisions ───────────────────────────────────────────────────────


class SaveDecisionsTests(unittest.TestCase):
    def test_save_creates_files_on_disk(self):
        agent = _build_agent()
        decisions = PbirReportDecisions(
            files={
                "Report.Report/.platform": '{"meta": "data"}',
                "Report.Report/definition/report.json": '{"report": true}',
            },
        )
        with managed_tempdir() as tmpdir:
            save_decisions(decisions.files, decisions.warnings, tmpdir, agent.logger)

            self.assertTrue((tmpdir / "Report.Report" / ".platform").exists())
            self.assertTrue((tmpdir / "Report.Report" / "definition" / "report.json").exists())

    def test_save_writes_warnings_json(self):
        agent = _build_agent()
        decisions = PbirReportDecisions(
            files={"f.json": "content"},
            warnings=[
                MigrationWarning(
                    severity="WARN",
                    code="W1",
                    message="test",
                    timestamp="2026-01-01T00:00:00Z",
                ),
            ],
        )
        with managed_tempdir() as tmpdir:
            save_decisions(decisions.files, decisions.warnings, tmpdir, agent.logger)

            warnings_file = tmpdir / "warnings.json"
            self.assertTrue(warnings_file.exists())
            data = json.loads(warnings_file.read_text(encoding="utf-8"))
            self.assertEqual(data["warning_count"], 1)

    def test_save_counts_pages_and_visuals(self):
        """save_decisions correctly counts page.json and visual.json files."""
        agent = _build_agent()
        decisions = PbirReportDecisions(
            files={
                "WB.Report/definition/pages/p1/page.json": "{}",
                "WB.Report/definition/pages/p1/visuals/v1/visual.json": "{}",
                "WB.Report/definition/pages/p1/visuals/v2/visual.json": "{}",
                "WB.Report/.platform": "{}",
            },
        )
        with managed_tempdir() as tmpdir:
            save_decisions(decisions.files, decisions.warnings, tmpdir, agent.logger)
            self.assertTrue((tmpdir / "WB.Report" / "definition" / "pages" / "p1" / "page.json").exists())
            self.assertTrue(
                (tmpdir / "WB.Report" / "definition" / "pages" / "p1" / "visuals" / "v1" / "visual.json").exists()
            )


# ── _recover_json ────────────────────────────────────────────────────────


class RecoverJsonTests(unittest.TestCase):
    """Tests for the JSON recovery fallback in _parse_response."""

    def test_literal_newlines_in_string_values(self):
        """Literal newlines inside JSON string values should be escaped."""
        # Build JSON with literal newlines inside a string value — this is
        # exactly what the LLM does when it embeds multi-line file content.
        malformed = '{"file.json": "line1\nline2\nline3"}'
        result = recover_malformed_json(malformed)
        self.assertIsNotNone(result)
        self.assertEqual(result["file.json"], "line1\nline2\nline3")

    def test_literal_tabs_in_string_values(self):
        """Literal tabs inside JSON string values should be escaped."""
        malformed = '{"file.tmdl": "measure\t= SUM(x)"}'
        result = recover_malformed_json(malformed)
        self.assertIsNotNone(result)
        self.assertEqual(result["file.tmdl"], "measure\t= SUM(x)")

    def test_literal_carriage_return_in_string_values(self):
        """Literal \\r inside JSON string values should be escaped."""
        malformed = '{"f": "a\r\nb"}'
        result = recover_malformed_json(malformed)
        self.assertIsNotNone(result)
        self.assertEqual(result["f"], "a\r\nb")

    def test_valid_json_passthrough(self):
        """Already valid JSON should parse fine too."""
        valid = '{"key": "value"}'
        result = recover_malformed_json(valid)
        self.assertIsNotNone(result)
        self.assertEqual(result["key"], "value")

    def test_hopelessly_broken_returns_none(self):
        """Totally broken text should return None, not raise."""
        self.assertIsNone(recover_malformed_json("not json at all {{{"))

    def test_non_dict_returns_none(self):
        """A JSON array should return None (we expect a dict)."""
        self.assertIsNone(recover_malformed_json("[1, 2, 3]"))

    def test_already_escaped_sequences_preserved(self):
        """Properly escaped \\n sequences must NOT be double-escaped."""
        valid = json.dumps({"f": "line1\\nline2"})
        result = recover_malformed_json(valid)
        self.assertIsNotNone(result)
        self.assertEqual(result["f"], "line1\\nline2")

    def test_mixed_escaped_and_literal(self):
        """Mix of escaped and literal newlines in the same value."""
        # "line1\\nline2" followed by a literal newline then "line3"
        malformed = '{"f": "line1\\\\nline2\nline3"}'
        result = recover_malformed_json(malformed)
        self.assertIsNotNone(result)
        self.assertIn("line3", result["f"])

    def test_invalid_escape_fixed(self):
        """Invalid escape sequences like \\S should be fixed by doubling the backslash."""
        malformed = '{"measures.tmdl": "measure \\Total = SUM(x)"}'
        result = recover_malformed_json(malformed)
        self.assertIsNotNone(result)
        self.assertIn("\\Total", result["measures.tmdl"])

    def test_invalid_escape_with_valid_escapes(self):
        """Mix of valid and invalid escapes in the same string."""
        malformed = '{"f": "line1\\nline2\\Stuff"}'
        result = recover_malformed_json(malformed)
        self.assertIsNotNone(result)
        self.assertIn("\n", result["f"])
        self.assertIn("\\Stuff", result["f"])

    def test_parse_response_uses_recovery(self):
        """_parse_response should succeed even with literal newlines."""
        malformed = '{"report/file.json": "{\n  \\"key\\": \\"val\\"\n}"}'
        result = parse_decisions_response(malformed)
        self.assertIn("report/file.json", result.files)


class ExtraDataRecoveryTests(unittest.TestCase):
    """Tests for the 'Extra data' recovery path in _parse_response."""

    def test_extra_text_after_closing_brace_recovered(self):
        """Valid JSON followed by trailing garbage should still parse."""
        payload = json.dumps({"report/file.json": "content"})
        extra = payload + "\n\nSome LLM explanation added after the JSON."
        result = parse_decisions_response(extra)
        self.assertIn("report/file.json", result.files)

    def test_second_json_object_trailing_dropped(self):
        """Valid JSON followed by a second JSON object should use only the first."""
        first = json.dumps({"report/file.json": "content"})
        second = json.dumps({"other/file.json": "other"})
        combined = first + second
        result = parse_decisions_response(combined)
        self.assertIn("report/file.json", result.files)
        self.assertNotIn("other/file.json", result.files)


# ── recover_truncated_json ───────────────────────────────────────────────


class RecoverTruncatedJsonTests(unittest.TestCase):
    """Tests for the truncated JSON recovery helper in parsing.py."""

    def test_last_comma_path_recovers(self):
        """JSON truncated mid-value after a comma recovers by cutting at the last complete pair."""
        from Tableau2PowerBI.agents.report_visuals.parsing import recover_truncated_json

        # {"file1.json": "content1","file2.json": "trun...
        text = '{"file1.json": "content1","file2.json": "truncated here without close'
        result = recover_truncated_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["file1.json"], "content1")

    def test_char_scan_path_recovers(self):
        """JSON truncated after a complete value recovers via char-by-char scan."""
        from Tableau2PowerBI.agents.report_visuals.parsing import recover_truncated_json

        text = '{"key1": "val1","key2": "val2"'
        result = recover_truncated_json(text)
        self.assertIsNotNone(result)
        # Char scan closes after the first complete key-value pair
        self.assertIn("key1", result)

    def test_warnings_removal_path_recovers(self):
        """JSON truncated during _warnings section recovers by dropping _warnings."""
        from Tableau2PowerBI.agents.report_visuals.parsing import recover_truncated_json

        text = '{"file1.json": "content","_warnings": [{"severity": "WARN", "code": "W1"'
        result = recover_truncated_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["file1.json"], "content")

    def test_already_complete_json_passes_through(self):
        """Valid JSON is returned as-is."""
        from Tableau2PowerBI.agents.report_visuals.parsing import recover_truncated_json

        text = '{"key": "value"}'
        result = recover_truncated_json(text)
        self.assertEqual(result, {"key": "value"})

    def test_hopelessly_broken_returns_none(self):
        """Completely broken text returns None."""
        from Tableau2PowerBI.agents.report_visuals.parsing import recover_truncated_json

        self.assertIsNone(recover_truncated_json("{broken"))


class NormaliseContentMalformedJsonTests(unittest.TestCase):
    """Test the malformed-JSON recovery path in normalise_content."""

    def test_malformed_escape_recovered_via_normalise(self):
        """normalise_content recovers a string with invalid backslash escapes."""
        malformed = '{"key": "line\\Stuff"}'
        result = normalise_content(malformed)
        parsed = json.loads(result)
        self.assertIn("Stuff", parsed["key"])

    def test_truncated_json_recovered_via_normalise(self):
        """normalise_content recovers a truncated JSON string."""
        truncated = '{"key1": "value1","key2": "truuuuunc'
        result = normalise_content(truncated)
        parsed = json.loads(result)
        self.assertEqual(parsed["key1"], "value1")


class ParseResponseTruncationTests(unittest.TestCase):
    """Test the truncation-recovery path in parse_response."""

    def test_truncated_response_recovered(self):
        """A truncated multi-file response recovers partial files."""
        full = {"report/file1.json": "content1", "report/file2.json": "content2"}
        text = json.dumps(full)
        # Truncate in the middle of file2's value
        truncated = text[: len(text) - 15]
        result = parse_decisions_response(truncated)
        self.assertIn("report/file1.json", result.files)
