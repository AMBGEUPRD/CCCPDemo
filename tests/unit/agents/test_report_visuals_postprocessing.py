"""Post-processing and assembly tests for the PBIR report visuals agent."""

import json
import logging
import unittest

from Tableau2PowerBI.agents.report_visuals import (
    PbirReportDecisions,
)
from Tableau2PowerBI.agents.report_visuals.postprocessing import (
    clamp_visual_bounds,
    ensure_pages_json,
    fix_pbir_enums,
    sanitize_visuals,
)

VISUAL_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/" "definition/visualContainer/2.7.0/schema.json"
)
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/" "definition/page/1.0.0/schema.json"
REPORT_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/" "definition/report/1.0.0/schema.json"

_TEST_LOGGER = logging.getLogger("test.pbir_visuals")
_DISPLAY_OPTION_MAP = {0: "FitToPage", 1: "FitToWidth", 2: "ActualSize"}
_LAYOUT_OPTIMIZATION_MAP = {0: "None", 1: "DynamicWidth"}

# ── _sanitize_visuals ───────────────────────────────────────────────────


def _stub_visual(name: str = "stub01") -> str:
    """Build a minimal visual stub with no position or visual block."""
    return json.dumps(
        {
            "$schema": VISUAL_SCHEMA,
            "name": name,
        }
    )


def _visual_no_position(name: str = "nopos01") -> str:
    """Build a visual with a visual block but missing position."""
    return json.dumps(
        {
            "$schema": VISUAL_SCHEMA,
            "name": name,
            "visual": {
                "visualType": "barChart",
                "query": {"queryState": {}},
            },
        }
    )


def _misplaced_visual_json() -> str:
    """Build a visual.json with drillFilter in query and filterConfig in visual."""
    return json.dumps(
        {
            "$schema": VISUAL_SCHEMA,
            "name": "vis01",
            "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300, "tabOrder": 0},
            "visual": {
                "visualType": "barChart",
                "query": {
                    "queryState": {},
                    "drillFilterOtherVisuals": True,
                },
                "filterConfig": {"filters": [{"name": "f1", "field": {}, "type": "Categorical"}]},
            },
        }
    )


def _make_visual_json(
    entity: str,
    prop: str,
    kind: str = "Measure",
    role: str = "Values",
) -> str:
    """Build a minimal but valid visual.json with one field projection."""
    return json.dumps(
        {
            "$schema": VISUAL_SCHEMA,
            "name": "vis01",
            "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300},
            "visual": {
                "visualType": "barChart",
                "query": {
                    "queryState": {
                        role: {
                            "projections": [
                                {
                                    "field": {
                                        kind: {
                                            "Expression": {"SourceRef": {"Entity": entity}},
                                            "Property": prop,
                                        }
                                    },
                                    "queryRef": f"{entity}.{prop}",
                                    "nativeQueryRef": prop,
                                    "active": True,
                                }
                            ]
                        }
                    }
                },
                "drillFilterOtherVisuals": True,
            },
            "filterConfig": {
                "filters": [
                    {
                        "name": "filter01",
                        "field": {
                            kind: {
                                "Expression": {"SourceRef": {"Entity": entity}},
                                "Property": prop,
                            }
                        },
                        "type": "Advanced",
                    }
                ]
            },
        }
    )


class SanitizeVisualsTests(unittest.TestCase):
    """Tests for the consolidated _sanitize_visuals post-processing step.

    Covers all three sub-fixes in a single pass:
    - Strip visual.config
    - Drop empty stubs / inject default position
    - Relocate drillFilterOtherVisuals and filterConfig
    """

    _VIS_PFX = "WB.Report/definition/pages/aaa/visuals"

    # ── config stripping ──────────────────────────────────────────────

    def test_strips_visual_config(self):
        """Visual.json with a config property has it stripped."""
        visual_content = json.dumps(
            {
                "$schema": "https://example.com/schema.json",
                "name": "abc123",
                "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300},
                "visual": {
                    "visualType": "barChart",
                    "query": {"queryState": {}},
                    "config": '{"version":"5.54","singleVisualConfig":{"vcObjects":{}}}',
                },
            }
        )
        decisions = PbirReportDecisions(
            files={
                f"{self._VIS_PFX}/bbb/visual.json": visual_content,
            }
        )

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[f"{self._VIS_PFX}/bbb/visual.json"])
        self.assertNotIn("config", out["visual"])
        self.assertEqual(metrics["configs_stripped"], 1)

    def test_leaves_clean_visual_unchanged(self):
        """Visual.json without a config property is left unchanged."""
        visual_content = json.dumps(
            {
                "$schema": "https://example.com/schema.json",
                "name": "abc123",
                "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300},
                "visual": {
                    "visualType": "barChart",
                    "query": {"queryState": {}},
                },
            }
        )
        decisions = PbirReportDecisions(
            files={
                f"{self._VIS_PFX}/bbb/visual.json": visual_content,
            }
        )

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[f"{self._VIS_PFX}/bbb/visual.json"])
        self.assertNotIn("config", out.get("visual", {}))
        self.assertEqual(metrics["configs_stripped"], 0)

    # ── incomplete visuals ────────────────────────────────────────────

    def test_drops_empty_stub(self):
        """A visual with only $schema and name is dropped entirely."""
        decisions = PbirReportDecisions(
            files={
                f"{self._VIS_PFX}/stub1/visual.json": _stub_visual("stub1"),
                "WB.Report/.platform": '{"meta": "data"}',
            }
        )

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        self.assertNotIn(
            f"{self._VIS_PFX}/stub1/visual.json",
            result.files,
        )
        self.assertIn("WB.Report/.platform", result.files)
        self.assertEqual(metrics["stubs_dropped"], 1)

    def test_injects_default_position(self):
        """A visual with a visual block but no position gets a default position."""
        decisions = PbirReportDecisions(
            files={
                f"{self._VIS_PFX}/v1/visual.json": _visual_no_position("v1"),
            }
        )

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[f"{self._VIS_PFX}/v1/visual.json"])
        self.assertIn("position", out)
        self.assertEqual(out["position"]["x"], 0)
        self.assertEqual(out["position"]["width"], 400)
        self.assertEqual(out["position"]["height"], 300)
        self.assertEqual(out["visual"]["visualType"], "barChart")
        self.assertEqual(metrics["positions_injected"], 1)

    def test_leaves_complete_visual_unchanged(self):
        """A visual with both position and visual is left as-is."""
        complete = _make_visual_json("Ordini", "Vendite", kind="Column")
        decisions = PbirReportDecisions(
            files={
                f"{self._VIS_PFX}/v1/visual.json": complete,
            }
        )

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        self.assertEqual(
            result.files[f"{self._VIS_PFX}/v1/visual.json"],
            complete,
        )
        self.assertEqual(sum(metrics.values()), 0)

    def test_handles_mix_of_complete_and_incomplete(self):
        """Complete ones kept, stub dropped, no-position repaired."""
        complete = _make_visual_json("Ordini", "Vendite", kind="Column")
        decisions = PbirReportDecisions(
            files={
                f"{self._VIS_PFX}/good/visual.json": complete,
                f"{self._VIS_PFX}/stub/visual.json": _stub_visual("stub"),
                f"{self._VIS_PFX}/nopos/visual.json": _visual_no_position("nopos"),
            }
        )

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        self.assertIn(f"{self._VIS_PFX}/good/visual.json", result.files)
        self.assertNotIn(f"{self._VIS_PFX}/stub/visual.json", result.files)
        self.assertIn(f"{self._VIS_PFX}/nopos/visual.json", result.files)
        out = json.loads(result.files[f"{self._VIS_PFX}/nopos/visual.json"])
        self.assertIn("position", out)
        self.assertEqual(metrics["stubs_dropped"], 1)
        self.assertEqual(metrics["positions_injected"], 1)

    # ── visual structure relocation ───────────────────────────────────

    def test_moves_drill_from_query_to_visual(self):
        """drillFilterOtherVisuals is moved from visual.query to visual."""
        decisions = PbirReportDecisions(
            files={
                f"{self._VIS_PFX}/v1/visual.json": _misplaced_visual_json(),
            }
        )

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[f"{self._VIS_PFX}/v1/visual.json"])
        self.assertTrue(out["visual"]["drillFilterOtherVisuals"])
        self.assertNotIn("drillFilterOtherVisuals", out["visual"]["query"])
        self.assertGreater(metrics["structure_fixed"], 0)

    def test_moves_drill_from_root_to_visual(self):
        """drillFilterOtherVisuals at document root is moved into visual."""
        root_drill = json.dumps(
            {
                "$schema": VISUAL_SCHEMA,
                "name": "vis02",
                "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300, "tabOrder": 0},
                "visual": {
                    "visualType": "barChart",
                    "query": {"queryState": {}},
                },
                "drillFilterOtherVisuals": True,
                "filterConfig": {"filters": []},
            }
        )
        decisions = PbirReportDecisions(
            files={
                f"{self._VIS_PFX}/v1/visual.json": root_drill,
            }
        )

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[f"{self._VIS_PFX}/v1/visual.json"])
        self.assertTrue(out["visual"]["drillFilterOtherVisuals"])
        self.assertNotIn("drillFilterOtherVisuals", out)
        self.assertGreater(metrics["structure_fixed"], 0)

    def test_moves_filterConfig_from_visual_to_root(self):
        """filterConfig is moved from visual to the root level."""
        decisions = PbirReportDecisions(
            files={
                f"{self._VIS_PFX}/v1/visual.json": _misplaced_visual_json(),
            }
        )

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[f"{self._VIS_PFX}/v1/visual.json"])
        self.assertIn("filterConfig", out)
        self.assertNotIn("filterConfig", out["visual"])
        self.assertEqual(len(out["filterConfig"]["filters"]), 1)

    def test_leaves_correctly_structured_visual_unchanged(self):
        """A visual with correct structure is left as-is."""
        correct = json.dumps(
            {
                "$schema": VISUAL_SCHEMA,
                "name": "vis01",
                "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300},
                "visual": {
                    "visualType": "barChart",
                    "query": {"queryState": {}},
                    "drillFilterOtherVisuals": True,
                },
                "filterConfig": {"filters": []},
            }
        )
        decisions = PbirReportDecisions(
            files={
                f"{self._VIS_PFX}/v1/visual.json": correct,
            }
        )

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        self.assertEqual(
            result.files[f"{self._VIS_PFX}/v1/visual.json"],
            correct,
        )
        self.assertEqual(sum(metrics.values()), 0)

    def test_non_visual_files_untouched(self):
        """Non-visual files pass through unchanged."""
        decisions = PbirReportDecisions(
            files={
                "WB.Report/.platform": '{"meta": "data"}',
                f"{self._VIS_PFX}/v1/visual.json": _misplaced_visual_json(),
            }
        )

        out_files, _ = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        self.assertEqual(result.files["WB.Report/.platform"], '{"meta": "data"}')

    def test_active_stripped_from_filter_field(self):
        """'active' key inside filterConfig.filters[].field is removed."""
        visual_with_active = json.dumps(
            {
                "$schema": VISUAL_SCHEMA,
                "name": "vis_active",
                "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300, "tabOrder": 0},
                "visual": {"visualType": "barChart", "query": {"queryState": {}}, "drillFilterOtherVisuals": True},
                "filterConfig": {
                    "filters": [
                        {
                            "name": "f1",
                            "field": {
                                "Column": {
                                    "Expression": {"SourceRef": {"Entity": "Orders"}},
                                    "Property": "Category",
                                },
                                "active": True,
                            },
                            "type": "Categorical",
                        }
                    ]
                },
            }
        )
        decisions = PbirReportDecisions(files={f"{self._VIS_PFX}/v1/visual.json": visual_with_active})

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        parsed = json.loads(result.files[f"{self._VIS_PFX}/v1/visual.json"])
        field = parsed["filterConfig"]["filters"][0]["field"]
        self.assertNotIn("active", field)
        self.assertIn("Column", field)
        self.assertGreater(metrics["structure_fixed"], 0)

    def test_bare_array_wrapped_in_projections(self):
        """queryState role that is a bare array gets wrapped in {"projections": [...]}."""
        visual_bare_array = json.dumps(
            {
                "$schema": VISUAL_SCHEMA,
                "name": "vis_bare",
                "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300, "tabOrder": 0},
                "visual": {
                    "visualType": "slicer",
                    "query": {
                        "queryState": {
                            "Category": [
                                {
                                    "field": {
                                        "Column": {
                                            "Expression": {"SourceRef": {"Entity": "Ordini"}},
                                            "Property": "Data ordine",
                                        }
                                    },
                                    "queryRef": "Ordini.Data ordine",
                                    "nativeQueryRef": "Data ordine",
                                    "active": True,
                                }
                            ]
                        }
                    },
                    "drillFilterOtherVisuals": True,
                },
                "filterConfig": {"filters": []},
            }
        )
        decisions = PbirReportDecisions(files={f"{self._VIS_PFX}/v1/visual.json": visual_bare_array})

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        parsed = json.loads(result.files[f"{self._VIS_PFX}/v1/visual.json"])
        category = parsed["visual"]["query"]["queryState"]["Category"]
        self.assertIsInstance(category, dict)
        self.assertIn("projections", category)
        self.assertIsInstance(category["projections"], list)
        self.assertEqual(len(category["projections"]), 1)
        self.assertEqual(category["projections"][0]["queryRef"], "Ordini.Data ordine")
        self.assertGreater(metrics["projections_wrapped"], 0)

    def test_correct_projections_object_untouched(self):
        """queryState role already wrapped in {"projections": [...]} is left as-is."""
        visual_correct = _make_visual_json("Ordini", "Vendite", kind="Column", role="Category")
        decisions = PbirReportDecisions(files={f"{self._VIS_PFX}/v1/visual.json": visual_correct})

        out_files, metrics = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        parsed = json.loads(result.files[f"{self._VIS_PFX}/v1/visual.json"])
        category = parsed["visual"]["query"]["queryState"]["Category"]
        self.assertIsInstance(category, dict)
        self.assertIn("projections", category)

    def test_malformed_escape_recovered(self):
        """visual.json with invalid backslash escapes is recovered."""
        # \P is not a valid JSON escape — simulates LLM stray backslash.
        bad_content = (
            '{"$schema":"x","name":"v","position":{"x":0,"y":0,"z":0,'
            '"width":400,"height":300,"tabOrder":0},"visual":{"visualType":"barChart",'
            '"query":{"queryState":{"Values":{"projections":[{"queryRef":'
            '"Sum(Ordini.Vendite\\Profitto)"}]}}},"drillFilterOtherVisuals":true},'
            '"filterConfig":{"filters":[]}}'
        )
        decisions = PbirReportDecisions(files={f"{self._VIS_PFX}/v1/visual.json": bad_content})

        out_files, _ = sanitize_visuals(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        output = result.files[f"{self._VIS_PFX}/v1/visual.json"]
        parsed = json.loads(output)
        self.assertEqual(parsed["visual"]["visualType"], "barChart")


# ── _fix_pbir_enums ────────────────────────────────────────────────────


class FixPbirEnumsTests(unittest.TestCase):
    """Tests for the _fix_pbir_enums post-processing step."""

    def test_converts_displayOption_int_to_string(self):
        """page.json with displayOption as an integer is converted to string."""
        page_content = json.dumps(
            {
                "$schema": PAGE_SCHEMA,
                "name": "abc123",
                "displayName": "Test Page",
                "width": 1280,
                "height": 720,
                "displayOption": 0,
            }
        )
        decisions = PbirReportDecisions(
            files={
                "WB.Report/definition/pages/aaa/page.json": page_content,
            }
        )

        out_files = fix_pbir_enums(decisions.files, _DISPLAY_OPTION_MAP, _LAYOUT_OPTIMIZATION_MAP, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files["WB.Report/definition/pages/aaa/page.json"])
        self.assertEqual(out["displayOption"], "FitToPage")

    def test_leaves_displayOption_string_unchanged(self):
        """page.json with displayOption already a string is left unchanged."""
        page_content = json.dumps(
            {
                "$schema": PAGE_SCHEMA,
                "name": "abc123",
                "displayName": "Test Page",
                "width": 1280,
                "height": 720,
                "displayOption": "FitToPage",
            }
        )
        decisions = PbirReportDecisions(
            files={
                "WB.Report/definition/pages/aaa/page.json": page_content,
            }
        )

        out_files = fix_pbir_enums(decisions.files, _DISPLAY_OPTION_MAP, _LAYOUT_OPTIMIZATION_MAP, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files["WB.Report/definition/pages/aaa/page.json"])
        self.assertEqual(out["displayOption"], "FitToPage")

    def test_converts_layoutOptimization_int_to_string(self):
        """report.json with layoutOptimization as an integer is converted to string."""
        report_content = json.dumps(
            {
                "$schema": REPORT_SCHEMA,
                "layoutOptimization": 0,
                "themeCollection": {},
            }
        )
        decisions = PbirReportDecisions(
            files={
                "WB.Report/definition/report.json": report_content,
            }
        )

        out_files = fix_pbir_enums(decisions.files, _DISPLAY_OPTION_MAP, _LAYOUT_OPTIMIZATION_MAP, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files["WB.Report/definition/report.json"])
        self.assertEqual(out["layoutOptimization"], "None")

    def test_leaves_layoutOptimization_string_unchanged(self):
        """report.json with layoutOptimization already a string is left unchanged."""
        report_content = json.dumps(
            {
                "$schema": REPORT_SCHEMA,
                "layoutOptimization": "None",
                "themeCollection": {},
            }
        )
        decisions = PbirReportDecisions(
            files={
                "WB.Report/definition/report.json": report_content,
            }
        )

        out_files = fix_pbir_enums(decisions.files, _DISPLAY_OPTION_MAP, _LAYOUT_OPTIMIZATION_MAP, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files["WB.Report/definition/report.json"])
        self.assertEqual(out["layoutOptimization"], "None")


# ── _ensure_pages_json ──────────────────────────────────────────────────


class EnsurePagesJsonTests(unittest.TestCase):
    """Tests for the _ensure_pages_json post-processing step."""

    def test_generates_pages_json_when_missing(self):
        """pages.json is created with correct pageOrder from existing pages."""
        decisions = PbirReportDecisions(
            files={
                "WB.Report/definition/pages/aaa111/page.json": "{}",
                "WB.Report/definition/pages/bbb222/page.json": "{}",
                "WB.Report/definition/pages/aaa111/visuals/v1/visual.json": "{}",
            }
        )

        out_files = ensure_pages_json(decisions.files, "WB", _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        pages_path = "WB.Report/definition/pages/pages.json"
        self.assertIn(pages_path, result.files)
        data = json.loads(result.files[pages_path])
        self.assertEqual(data["pageOrder"], ["aaa111", "bbb222"])
        self.assertEqual(data["activePageName"], "aaa111")
        self.assertIn("pagesMetadata", data["$schema"])

    def test_leaves_existing_pages_json_untouched(self):
        """If the LLM already generated pages.json, don't overwrite it."""
        existing = '{"pageOrder": ["custom"], "activePageName": "custom"}'
        decisions = PbirReportDecisions(
            files={
                "WB.Report/definition/pages/pages.json": existing,
                "WB.Report/definition/pages/aaa111/page.json": "{}",
            }
        )

        out_files = ensure_pages_json(decisions.files, "WB", _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        self.assertEqual(
            result.files["WB.Report/definition/pages/pages.json"],
            existing,
        )

    def test_no_pages_does_not_crash(self):
        """If there are no page.json files, pages.json is not generated."""
        decisions = PbirReportDecisions(
            files={
                "WB.Report/.platform": "{}",
            }
        )

        out_files = ensure_pages_json(decisions.files, "WB", _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        self.assertNotIn(
            "WB.Report/definition/pages/pages.json",
            result.files,
        )


# ── _clamp_visual_bounds ────────────────────────────────────────────────


class ClampVisualBoundsTests(unittest.TestCase):
    """Tests for the _clamp_visual_bounds post-processing step."""

    _PAGE_ID = "abc123def456abc123de"
    _VIS_ID = "xyz123abc456xyz123ab"

    def _page_path(self) -> str:
        return f"WorkbookName.Report/definition/pages/{self._PAGE_ID}/page.json"

    def _visual_path(self) -> str:
        return f"WorkbookName.Report/definition/pages/{self._PAGE_ID}" f"/visuals/{self._VIS_ID}/visual.json"

    def test_clamp_visual_bounds_expands_page_height(self):
        """Page height is expanded when a visual overflows."""
        page_content = json.dumps(
            {
                "$schema": "https://example.com/schema.json",
                "name": self._PAGE_ID,
                "displayName": "Dashboard 1",
                "width": 1280,
                "height": 500,
            }
        )
        visual_content = json.dumps(
            {
                "$schema": "https://example.com/schema.json",
                "name": self._VIS_ID,
                "position": {"x": 10, "y": 600, "z": 0, "width": 300, "height": 300},
                "visual": {"visualType": "barChart", "query": {"queryState": {}}},
            }
        )
        decisions = PbirReportDecisions(
            files={
                self._page_path(): page_content,
                self._visual_path(): visual_content,
            }
        )

        out_files = clamp_visual_bounds(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        page_out = json.loads(result.files[self._page_path()])
        # y(600) + height(300) = 900, which exceeds 500 -> max(900, 720) = 900
        self.assertEqual(page_out["height"], 900)

    def test_clamp_visual_bounds_leaves_valid_page_unchanged(self):
        """Page height is not changed when all visuals fit."""
        page_content = json.dumps(
            {
                "$schema": "https://example.com/schema.json",
                "name": self._PAGE_ID,
                "displayName": "Dashboard 1",
                "width": 1280,
                "height": 800,
            }
        )
        visual_content = json.dumps(
            {
                "$schema": "https://example.com/schema.json",
                "name": self._VIS_ID,
                "position": {"x": 10, "y": 100, "z": 0, "width": 300, "height": 200},
                "visual": {"visualType": "barChart", "query": {"queryState": {}}},
            }
        )
        decisions = PbirReportDecisions(
            files={
                self._page_path(): page_content,
                self._visual_path(): visual_content,
            }
        )

        out_files = clamp_visual_bounds(decisions.files, _TEST_LOGGER)
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        page_out = json.loads(result.files[self._page_path()])
        # y(100) + height(200) = 300, well within 800 -> unchanged
        self.assertEqual(page_out["height"], 800)


# ── Additional fix_pbir_enums edge cases ─────────────────────────────────


class FixPbirEnumsEdgeCaseTests(unittest.TestCase):
    """Cover edge cases in fix_pbir_enums not hit by the main tests."""

    def test_bad_json_page_skipped(self):
        """page.json with invalid JSON content is passed through unchanged."""
        bad_content = "not valid json {{"
        files = {"WB.Report/definition/pages/aaa/page.json": bad_content}
        result = fix_pbir_enums(files, _DISPLAY_OPTION_MAP, _LAYOUT_OPTIMIZATION_MAP, _TEST_LOGGER)
        self.assertEqual(result["WB.Report/definition/pages/aaa/page.json"], bad_content)

    def test_bad_json_report_skipped(self):
        """report.json with invalid JSON content is passed through unchanged."""
        bad_content = "not valid json"
        files = {"WB.Report/definition/report.json": bad_content}
        result = fix_pbir_enums(files, _DISPLAY_OPTION_MAP, _LAYOUT_OPTIMIZATION_MAP, _TEST_LOGGER)
        self.assertEqual(result["WB.Report/definition/report.json"], bad_content)

    def test_unknown_displayOption_int_warns(self):
        """Unknown int displayOption logs warning and leaves unchanged."""
        page_content = json.dumps({"displayOption": 99})
        files = {"WB.Report/definition/pages/aaa/page.json": page_content}
        result = fix_pbir_enums(files, _DISPLAY_OPTION_MAP, _LAYOUT_OPTIMIZATION_MAP, _TEST_LOGGER)
        parsed = json.loads(result["WB.Report/definition/pages/aaa/page.json"])
        self.assertEqual(parsed["displayOption"], 99)

    def test_unknown_layoutOptimization_int_warns(self):
        """Unknown int layoutOptimization logs warning and leaves unchanged."""
        report_content = json.dumps({"layoutOptimization": 99})
        files = {"WB.Report/definition/report.json": report_content}
        result = fix_pbir_enums(files, _DISPLAY_OPTION_MAP, _LAYOUT_OPTIMIZATION_MAP, _TEST_LOGGER)
        parsed = json.loads(result["WB.Report/definition/report.json"])
        self.assertEqual(parsed["layoutOptimization"], 99)

    def test_non_page_non_report_files_unchanged(self):
        """Files that are not page.json or report.json pass through."""
        files = {
            "WB.Report/.platform": '{"meta": true}',
            "WB.Report/definition/version.json": '{"v": 1}',
        }
        result = fix_pbir_enums(files, _DISPLAY_OPTION_MAP, _LAYOUT_OPTIMIZATION_MAP, _TEST_LOGGER)
        self.assertEqual(result["WB.Report/.platform"], '{"meta": true}')


# ── Additional sanitize_visuals edge cases ───────────────────────────────


class SanitizeVisualsEdgeCaseTests(unittest.TestCase):
    """Cover edge cases in sanitize_visuals not hit by the main tests."""

    _VIS_PFX = "WB.Report/definition/pages/aaa/visuals"

    def test_unrecoverable_bad_json_skipped(self):
        """visual.json with totally unrecoverable JSON is passed through."""
        files = {f"{self._VIS_PFX}/v1/visual.json": "{{{{not recoverable}}}}"}
        out_files, _ = sanitize_visuals(files, _TEST_LOGGER)
        self.assertEqual(out_files[f"{self._VIS_PFX}/v1/visual.json"], "{{{{not recoverable}}}}")


# ── Additional clamp_visual_bounds edge cases ────────────────────────────


class ClampVisualBoundsEdgeCaseTests(unittest.TestCase):
    """Cover edge cases in clamp_visual_bounds not hit by the main tests."""

    def test_bad_page_json_skipped(self):
        """page.json with bad JSON does not crash clamping."""
        files = {
            "WB.Report/definition/pages/p1/page.json": "not json",
            "WB.Report/definition/pages/p1/visuals/v1/visual.json": json.dumps(
                {"position": {"x": 0, "y": 1000, "height": 500}}
            ),
        }
        result = clamp_visual_bounds(files, _TEST_LOGGER)
        self.assertEqual(result["WB.Report/definition/pages/p1/page.json"], "not json")

    def test_bad_visual_json_skipped(self):
        """visual.json with bad JSON does not crash clamping."""
        page = json.dumps({"height": 720})
        files = {
            "WB.Report/definition/pages/p1/page.json": page,
            "WB.Report/definition/pages/p1/visuals/v1/visual.json": "not json",
        }
        result = clamp_visual_bounds(files, _TEST_LOGGER)
        # Page height unchanged because visual couldn't be parsed
        parsed = json.loads(result["WB.Report/definition/pages/p1/page.json"])
        self.assertEqual(parsed["height"], 720)

    def test_page_with_no_visuals_unchanged(self):
        """A page with no matching visuals is left unchanged."""
        page = json.dumps({"height": 500})
        files = {
            "WB.Report/definition/pages/p1/page.json": page,
        }
        result = clamp_visual_bounds(files, _TEST_LOGGER)
        parsed = json.loads(result["WB.Report/definition/pages/p1/page.json"])
        self.assertEqual(parsed["height"], 500)


# ── build_field_index_from_tdd ───────────────────────────────────────────


class BuildFieldIndexFromTddTests(unittest.TestCase):
    """Tests for build_field_index_from_tdd helper."""

    def test_builds_measure_and_column_sets(self):
        from Tableau2PowerBI.agents.report_visuals.postprocessing import (
            build_field_index_from_tdd,
        )

        tdd_sm = {
            "tables": [
                {"name": "Orders", "columns": [{"name": "Amount"}, {"name": "Date"}]},
            ],
        }
        tdd_dax = {
            "measures": [
                {"owner_table": "Orders", "caption": "Total Sales"},
            ],
        }
        tdd_report = {
            "entity_resolution": {
                "calculated_field_map": {"Calculation_1": "Total Sales"},
            },
        }
        calc_mapping, measure_set, column_set = build_field_index_from_tdd(
            tdd_sm,
            tdd_dax,
            tdd_report,
        )
        self.assertEqual(calc_mapping, {"Calculation_1": "Total Sales"})
        self.assertIn("Orders.Total Sales", measure_set)
        self.assertIn("Orders.Amount", column_set)
        self.assertIn("Orders.Date", column_set)

    def test_empty_inputs(self):
        from Tableau2PowerBI.agents.report_visuals.postprocessing import (
            build_field_index_from_tdd,
        )

        calc_mapping, measure_set, column_set = build_field_index_from_tdd({}, {}, {})
        self.assertEqual(calc_mapping, {})
        self.assertEqual(measure_set, set())
        self.assertEqual(column_set, set())


# ── fix_field_references ─────────────────────────────────────────────────


class FixFieldReferencesTests(unittest.TestCase):
    """Tests for the fix_field_references post-processor."""

    _VIS_PFX = "WB.Report/definition/pages/aaa/visuals"

    def test_resolves_calc_name_in_projection(self):
        from Tableau2PowerBI.agents.report_visuals.postprocessing import (
            fix_field_references,
        )

        visual = _make_visual_json("Orders", "Calculation_1", kind="Measure")
        files = {f"{self._VIS_PFX}/v1/visual.json": visual}
        calc_mapping = {"Calculation_1": "Total Sales"}
        measure_set = {"Orders.Total Sales"}

        out_files, metrics = fix_field_references(
            files,
            calc_mapping,
            measure_set,
            set(),
            _TEST_LOGGER,
        )
        parsed = json.loads(out_files[f"{self._VIS_PFX}/v1/visual.json"])
        proj = parsed["visual"]["query"]["queryState"]["Values"]["projections"][0]
        self.assertEqual(proj["field"]["Measure"]["Property"], "Total Sales")
        self.assertEqual(proj["queryRef"], "Orders.Total Sales")
        self.assertEqual(proj["nativeQueryRef"], "Total Sales")
        self.assertGreater(metrics["calc_names_resolved"], 0)

    def test_fixes_column_to_measure_kind(self):
        from Tableau2PowerBI.agents.report_visuals.postprocessing import (
            fix_field_references,
        )

        visual = _make_visual_json("Orders", "Total Sales", kind="Column")
        files = {f"{self._VIS_PFX}/v1/visual.json": visual}
        measure_set = {"Orders.Total Sales"}

        out_files, metrics = fix_field_references(
            files,
            {},
            measure_set,
            set(),
            _TEST_LOGGER,
        )
        parsed = json.loads(out_files[f"{self._VIS_PFX}/v1/visual.json"])
        proj = parsed["visual"]["query"]["queryState"]["Values"]["projections"][0]
        self.assertIn("Measure", proj["field"])
        self.assertNotIn("Column", proj["field"])
        self.assertGreater(metrics["field_kinds_fixed"], 0)

    def test_non_visual_files_unchanged(self):
        from Tableau2PowerBI.agents.report_visuals.postprocessing import (
            fix_field_references,
        )

        files = {"WB.Report/.platform": '{"meta": true}'}
        out_files, metrics = fix_field_references(
            files,
            {},
            set(),
            set(),
            _TEST_LOGGER,
        )
        self.assertEqual(out_files["WB.Report/.platform"], '{"meta": true}')
        self.assertEqual(sum(metrics.values()), 0)

    def test_bad_visual_json_skipped(self):
        from Tableau2PowerBI.agents.report_visuals.postprocessing import (
            fix_field_references,
        )

        files = {f"{self._VIS_PFX}/v1/visual.json": "not json"}
        out_files, metrics = fix_field_references(
            files,
            {},
            set(),
            set(),
            _TEST_LOGGER,
        )
        self.assertEqual(out_files[f"{self._VIS_PFX}/v1/visual.json"], "not json")
