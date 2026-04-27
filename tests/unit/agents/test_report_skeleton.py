"""Tests for the Report Skeleton Agent (Pass 1 of hybrid generation).

Covers: Pydantic model validation, response parsing, and the skeleton
contract — all without LLM calls.
"""

import json
import logging
import unittest

from pydantic import ValidationError

from Tableau2PowerBI.agents.report_skeleton import (
    ReportSkeleton,
    ReportSkeletonAgent,
    SkeletonPage,
    SkeletonVisual,
    VisualPosition,
    parse_skeleton_response,
)
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.models import MigrationWarning

# ── Helpers ───────────────────────────────────────────────────────────────


def _valid_position(**overrides) -> dict:
    """Build a valid VisualPosition dict with optional overrides."""
    base = {"x": 10, "y": 20, "width": 400, "height": 300, "tab_order": 0}
    base.update(overrides)
    return base


def _valid_visual(**overrides) -> dict:
    """Build a valid SkeletonVisual dict with optional overrides."""
    base = {
        "worksheet_name": "Sheet1",
        "visual_type": "barChart",
        "hex_id": "a1b2c3d4e5f6a7b8c9d0",
        "position": _valid_position(),
    }
    base.update(overrides)
    return base


def _valid_page(**overrides) -> dict:
    """Build a valid SkeletonPage dict with optional overrides."""
    base = {
        "dashboard_name": "Dashboard1",
        "display_name": "Dashboard 1",
        "hex_id": "1a2b3c4d5e6f7a8b9c0d",
        "width": 1280,
        "height": 720,
        "visuals": [_valid_visual()],
    }
    base.update(overrides)
    return base


def _valid_skeleton(**overrides) -> dict:
    """Build a valid ReportSkeleton dict with optional overrides."""
    base = {"pages": [_valid_page()], "warnings": []}
    base.update(overrides)
    return base


def _build_skeleton_agent():
    """Construct a ReportSkeletonAgent without Azure dependencies."""
    agent = object.__new__(ReportSkeletonAgent)
    agent.skill_name = "report_skeleton_agent"
    agent.settings = AgentSettings(project_endpoint="https://example.test")
    agent.logger = logging.getLogger("test.report_skeleton")
    return agent


# ── VisualPosition model tests ───────────────────────────────────────────


class VisualPositionTests(unittest.TestCase):
    def test_valid_position(self):
        pos = VisualPosition(**_valid_position())
        self.assertEqual(pos.x, 10)
        self.assertEqual(pos.width, 400)

    def test_negative_x_rejected(self):
        with self.assertRaises(ValidationError):
            VisualPosition(**_valid_position(x=-1))

    def test_zero_width_rejected(self):
        with self.assertRaises(ValidationError):
            VisualPosition(**_valid_position(width=0))

    def test_zero_height_rejected(self):
        with self.assertRaises(ValidationError):
            VisualPosition(**_valid_position(height=0))


# ── SkeletonVisual model tests ───────────────────────────────────────────


class SkeletonVisualTests(unittest.TestCase):
    def test_valid_visual(self):
        vis = SkeletonVisual(**_valid_visual())
        self.assertEqual(vis.worksheet_name, "Sheet1")
        self.assertEqual(vis.visual_type, "barChart")

    def test_short_hex_id_rejected(self):
        with self.assertRaises(ValidationError):
            SkeletonVisual(**_valid_visual(hex_id="abc123"))

    def test_uppercase_hex_id_rejected(self):
        with self.assertRaises(ValidationError):
            SkeletonVisual(**_valid_visual(hex_id="A1B2C3D4E5F6A7B8C9D0"))

    def test_non_hex_chars_rejected(self):
        with self.assertRaises(ValidationError):
            SkeletonVisual(**_valid_visual(hex_id="zzzzzzzzzzzzzzzzzzzz"))

    def test_empty_visual_type_rejected(self):
        with self.assertRaises(ValidationError):
            SkeletonVisual(**_valid_visual(visual_type=""))

    def test_whitespace_visual_type_rejected(self):
        with self.assertRaises(ValidationError):
            SkeletonVisual(**_valid_visual(visual_type="   "))


# ── SkeletonPage model tests ─────────────────────────────────────────────


class SkeletonPageTests(unittest.TestCase):
    def test_valid_page(self):
        page = SkeletonPage(**_valid_page())
        self.assertEqual(page.dashboard_name, "Dashboard1")
        self.assertEqual(len(page.visuals), 1)

    def test_invalid_hex_id(self):
        with self.assertRaises(ValidationError):
            SkeletonPage(**_valid_page(hex_id="too_short"))

    def test_zero_height_rejected(self):
        with self.assertRaises(ValidationError):
            SkeletonPage(**_valid_page(height=0))

    def test_empty_visuals_allowed(self):
        """A page with no visuals is valid (empty dashboard)."""
        page = SkeletonPage(**_valid_page(visuals=[]))
        self.assertEqual(len(page.visuals), 0)


# ── ReportSkeleton model tests ───────────────────────────────────────────


class ReportSkeletonTests(unittest.TestCase):
    def test_valid_skeleton(self):
        skel = ReportSkeleton(**_valid_skeleton())
        self.assertEqual(len(skel.pages), 1)
        self.assertEqual(skel.warnings, [])

    def test_empty_pages_rejected(self):
        with self.assertRaises(ValidationError):
            ReportSkeleton(**_valid_skeleton(pages=[]))

    def test_warnings_default_to_empty(self):
        data = _valid_skeleton()
        del data["warnings"]
        skel = ReportSkeleton(**data)
        self.assertEqual(skel.warnings, [])

    def test_valid_with_warnings(self):
        skel = ReportSkeleton(
            pages=[SkeletonPage(**_valid_page())],
            warnings=[
                MigrationWarning(
                    severity="WARN",
                    code="WORKSHEET_ORPHANED",
                    message="test",
                    timestamp="2026-01-01T00:00:00Z",
                ),
            ],
        )
        self.assertEqual(len(skel.warnings), 1)

    def test_multiple_pages(self):
        page1 = _valid_page(hex_id="1a2b3c4d5e6f7a8b9c0d")
        page2 = _valid_page(
            dashboard_name="Dash2",
            hex_id="2b3c4d5e6f7a8b9c0d1e",
        )
        skel = ReportSkeleton(
            pages=[
                SkeletonPage(**page1),
                SkeletonPage(**page2),
            ]
        )
        self.assertEqual(len(skel.pages), 2)


# ── _parse_response tests ────────────────────────────────────────────────


class ParseResponseTests(unittest.TestCase):
    def test_valid_json(self):
        raw = json.dumps(_valid_skeleton())
        result = parse_skeleton_response(raw)
        self.assertEqual(len(result.pages), 1)
        self.assertEqual(
            result.pages[0].visuals[0].visual_type,
            "barChart",
        )

    def test_strips_markdown_fences(self):
        raw = "```json\n" + json.dumps(_valid_skeleton()) + "\n```"
        result = parse_skeleton_response(raw)
        self.assertEqual(len(result.pages), 1)

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            parse_skeleton_response("not json at all")

    def test_non_object_raises(self):
        with self.assertRaises(ValueError):
            parse_skeleton_response("[1, 2, 3]")

    def test_normalises_underscore_warnings_key(self):
        """LLM may use _warnings instead of warnings."""
        data = _valid_skeleton()
        data.pop("warnings")
        data["_warnings"] = [
            {"severity": "WARN", "code": "TEST", "message": "test"},
        ]
        result = parse_skeleton_response(json.dumps(data))
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.warnings[0].code, "TEST")

    def test_empty_pages_rejected_after_parse(self):
        data = _valid_skeleton(pages=[])
        with self.assertRaises(ValueError):
            parse_skeleton_response(json.dumps(data))

    def test_invalid_hex_in_parsed_data_rejected(self):
        data = _valid_skeleton()
        data["pages"][0]["hex_id"] = "INVALID_HEX"
        with self.assertRaises((ValueError, ValidationError)):
            parse_skeleton_response(json.dumps(data))


if __name__ == "__main__":
    unittest.main()
