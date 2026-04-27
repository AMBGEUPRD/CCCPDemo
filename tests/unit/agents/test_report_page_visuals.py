"""Tests for the Report Page Visuals Agent (Pass 2 of hybrid generation).

Covers: Pydantic model validation, response parsing, content normalisation,
and truncation recovery — all without LLM calls.
"""

import json
import logging
import unittest

from pydantic import ValidationError

from Tableau2PowerBI.agents.report_page_visuals import (
    PageVisualsOutput,
    ReportPageVisualsAgent,
    parse_page_visuals_response,
)
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.models import MigrationWarning

# ── Helpers ───────────────────────────────────────────────────────────────


def _minimal_visual_json(hex_id: str = "a1b2c3d4e5f6a7b8c9d0") -> dict:
    """Build a minimal visual.json dict."""
    return {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/"
            "fabric/item/report/definition/"
            "visualContainer/2.7.0/schema.json"
        ),
        "name": hex_id,
        "position": {
            "x": 10,
            "y": 20,
            "z": 0,
            "width": 400,
            "height": 300,
            "tabOrder": 0,
        },
        "visual": {
            "visualType": "barChart",
            "query": {"queryState": {}},
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": {"filters": []},
    }


def _page_response(num_visuals: int = 1) -> dict:
    """Build a valid page visuals response dict."""
    result = {}
    for i in range(num_visuals):
        hex_id = f"a{i:019x}"
        result[hex_id] = json.dumps(_minimal_visual_json(hex_id))
    result["_warnings"] = []
    return result


def _build_page_visuals_agent():
    """Construct a ReportPageVisualsAgent without Azure dependencies."""
    agent = object.__new__(ReportPageVisualsAgent)
    agent.skill_name = "report_page_visuals_agent"
    agent.settings = AgentSettings(project_endpoint="https://example.test")
    agent.logger = logging.getLogger("test.report_page_visuals")
    return agent


# ── PageVisualsOutput model tests ─────────────────────────────────────────


class PageVisualsOutputTests(unittest.TestCase):
    def test_valid_minimal(self):
        d = PageVisualsOutput(visuals={"hex1": "content"})
        self.assertEqual(len(d.visuals), 1)
        self.assertEqual(d.warnings, [])

    def test_empty_visuals_rejected(self):
        with self.assertRaises(ValidationError):
            PageVisualsOutput(visuals={})

    def test_warnings_default_to_empty(self):
        d = PageVisualsOutput(visuals={"hex1": "c"})
        self.assertEqual(d.warnings, [])

    def test_valid_with_warnings(self):
        d = PageVisualsOutput(
            visuals={"hex1": "c"},
            warnings=[
                MigrationWarning(
                    severity="WARN",
                    code="TEST",
                    message="test",
                    timestamp="2026-01-01T00:00:00Z",
                ),
            ],
        )
        self.assertEqual(len(d.warnings), 1)

    def test_multiple_visuals(self):
        d = PageVisualsOutput(visuals={"h1": "c1", "h2": "c2", "h3": "c3"})
        self.assertEqual(len(d.visuals), 3)


# ── _parse_response tests ────────────────────────────────────────────────


class ParseResponseTests(unittest.TestCase):
    def test_valid_json(self):
        raw = json.dumps(_page_response(2))
        result = parse_page_visuals_response(raw)
        self.assertEqual(len(result.visuals), 2)
        self.assertEqual(result.warnings, [])

    def test_strips_markdown_fences(self):
        raw = "```json\n" + json.dumps(_page_response()) + "\n```"
        result = parse_page_visuals_response(raw)
        self.assertEqual(len(result.visuals), 1)

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            parse_page_visuals_response("not json")

    def test_non_object_raises(self):
        with self.assertRaises(ValueError):
            parse_page_visuals_response("[1, 2]")

    def test_visual_content_as_dict_normalised(self):
        """LLM may return visual content as a dict instead of string."""
        resp = {
            "a1b2c3d4e5f6a7b8c9d0": _minimal_visual_json(),
            "_warnings": [],
        }
        result = parse_page_visuals_response(json.dumps(resp))
        self.assertEqual(len(result.visuals), 1)
        # Content should be re-serialised as a formatted string.
        content = result.visuals["a1b2c3d4e5f6a7b8c9d0"]
        parsed = json.loads(content)
        self.assertEqual(parsed["visual"]["visualType"], "barChart")

    def test_warnings_extracted(self):
        resp = _page_response()
        resp["_warnings"] = [
            {"severity": "WARN", "code": "TEST", "message": "msg"},
        ]
        result = parse_page_visuals_response(json.dumps(resp))
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.warnings[0].code, "TEST")

    def test_no_visuals_rejected(self):
        """Response with only _warnings and no visual keys fails."""
        resp = {"_warnings": []}
        with self.assertRaises((ValueError, ValidationError)):
            parse_page_visuals_response(json.dumps(resp))


# ── _recover_truncated_json tests ─────────────────────────────────────────


class RecoverTruncatedJsonTests(unittest.TestCase):
    def test_valid_json_recovered(self):
        data = '{"key1":"val1","key2":"val2"}'
        result = ReportPageVisualsAgent._recover_truncated_json(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["key1"], "val1")

    def test_truncated_at_value(self):
        data = '{"hex1":"complete_value","hex2":"trunc'
        result = ReportPageVisualsAgent._recover_truncated_json(data)
        self.assertIsNotNone(result)
        self.assertIn("hex1", result)
        self.assertNotIn("hex2", result)

    def test_unrecoverable_returns_none(self):
        result = ReportPageVisualsAgent._recover_truncated_json("garbage")
        self.assertIsNone(result)


# ── _normalise_visual_content tests ──────────────────────────────────────


class NormaliseVisualContentTests(unittest.TestCase):
    def test_dict_to_json_string(self):
        result = ReportPageVisualsAgent._normalise_visual_content(
            {"key": "value"},
        )
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "value")

    def test_json_string_reformatted(self):
        compact = '{"key":"value"}'
        result = ReportPageVisualsAgent._normalise_visual_content(compact)
        self.assertIn("\n", result)  # Re-serialised with indent

    def test_plain_string_returned_as_is(self):
        text = "not json content"
        result = ReportPageVisualsAgent._normalise_visual_content(text)
        self.assertEqual(result, text)

    def test_non_string_converted(self):
        result = ReportPageVisualsAgent._normalise_visual_content(42)
        self.assertEqual(result, "42")

    def test_invalid_escape_recovered(self):
        """Stray backslashes in JSON string values are fixed."""
        # Simulates LLM producing a queryRef like "Sum(Ordini.Vendite\Profitto)"
        # where \P is an invalid JSON escape.
        bad_json = (
            '{"visual":{"query":{"queryState":{"Values":{"projections":'
            '[{"queryRef":"Sum(Ordini.Vendite\\Profitto)"}]}}}}}'
        )
        result = ReportPageVisualsAgent._normalise_visual_content(bad_json)
        parsed = json.loads(result)
        qr = parsed["visual"]["query"]["queryState"]["Values"]["projections"][0]["queryRef"]
        self.assertIn("Vendite\\Profitto", qr)


# ── _fix_visual_structure tests ──────────────────────────────────────────


class FixVisualStructureTests(unittest.TestCase):
    """Verify the structural post-processing applied to each visual."""

    def test_drillfilter_moved_from_root_to_visual(self):
        data = {
            "visual": {"visualType": "barChart", "query": {"queryState": {}}},
            "drillFilterOtherVisuals": True,
        }
        result = ReportPageVisualsAgent._fix_visual_structure(data)
        self.assertNotIn("drillFilterOtherVisuals", result)
        self.assertTrue(result["visual"]["drillFilterOtherVisuals"])

    def test_drillfilter_moved_from_query_to_visual(self):
        data = {
            "visual": {
                "visualType": "barChart",
                "query": {
                    "queryState": {},
                    "drillFilterOtherVisuals": True,
                },
            },
        }
        result = ReportPageVisualsAgent._fix_visual_structure(data)
        self.assertNotIn("drillFilterOtherVisuals", result["visual"]["query"])
        self.assertTrue(result["visual"]["drillFilterOtherVisuals"])

    def test_filterconfig_moved_from_visual_to_root(self):
        data = {
            "visual": {
                "visualType": "barChart",
                "filterConfig": {"filters": []},
            },
        }
        result = ReportPageVisualsAgent._fix_visual_structure(data)
        self.assertNotIn("filterConfig", result["visual"])
        self.assertEqual(result["filterConfig"], {"filters": []})

    def test_visual_config_stripped(self):
        data = {
            "visual": {
                "visualType": "barChart",
                "config": '{"legacy": true}',
                "query": {"queryState": {}},
            },
        }
        result = ReportPageVisualsAgent._fix_visual_structure(data)
        self.assertNotIn("config", result["visual"])

    def test_active_stripped_from_filterconfig_field(self):
        data = {
            "visual": {"visualType": "barChart"},
            "filterConfig": {
                "filters": [
                    {
                        "name": "abcdef0123",
                        "field": {
                            "Column": {"Expression": {}, "Property": "F"},
                            "active": True,
                        },
                        "type": "Categorical",
                    },
                ],
            },
        }
        result = ReportPageVisualsAgent._fix_visual_structure(data)
        self.assertNotIn("active", result["filterConfig"]["filters"][0]["field"])

    def test_bare_array_wrapped_in_querystate(self):
        data = {
            "visual": {
                "visualType": "barChart",
                "query": {
                    "queryState": {
                        "Category": [{"field": {"Column": {}}}],
                    },
                },
            },
        }
        result = ReportPageVisualsAgent._fix_visual_structure(data)
        role = result["visual"]["query"]["queryState"]["Category"]
        self.assertIsInstance(role, dict)
        self.assertIn("projections", role)

    def test_no_visual_key_returns_unchanged(self):
        data = {"$schema": "...", "name": "abc"}
        result = ReportPageVisualsAgent._fix_visual_structure(data)
        self.assertEqual(result, data)

    def test_normalise_applies_structure_fix(self):
        """_normalise_visual_content must apply _fix_visual_structure."""
        bad = {
            "visual": {"visualType": "barChart", "query": {"queryState": {}}},
            "drillFilterOtherVisuals": True,
        }
        result = ReportPageVisualsAgent._normalise_visual_content(bad)
        parsed = json.loads(result)
        self.assertNotIn("drillFilterOtherVisuals", parsed)
        self.assertTrue(parsed["visual"]["drillFilterOtherVisuals"])


if __name__ == "__main__":
    unittest.main()
