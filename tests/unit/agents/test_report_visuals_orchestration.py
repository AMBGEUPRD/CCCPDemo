"""Orchestration and assembly tests for the PBIR report visuals agent."""

import json
import unittest

from Tableau2PowerBI.agents.report_visuals.orchestration import (
    assemble_report,
    build_skeleton_from_tdd,
    filter_metadata_for_page,
    generate_static_files,
)
from Tableau2PowerBI.core.models import MigrationWarning


class FilterMetadataForPageTests(unittest.TestCase):
    """Tests for the orchestrator's page-metadata filtering."""

    def test_filters_to_page_worksheets(self):
        """Only worksheets referenced by the skeleton page are kept."""
        from Tableau2PowerBI.agents.report_skeleton import SkeletonPage, SkeletonVisual, VisualPosition

        page = SkeletonPage(
            dashboard_name="Dash1",
            display_name="Dash 1",
            hex_id="a1b2c3d4e5f6a7b8c9d0",
            height=720,
            visuals=[
                SkeletonVisual(
                    worksheet_name="Sheet1",
                    visual_type="barChart",
                    hex_id="b1b2c3d4e5f6a7b8c9d0",
                    position=VisualPosition(x=0, y=0, width=400, height=300, tab_order=0),
                ),
            ],
        )
        report_input = {
            "datasource_index": {"fed.1": "DS1"},
            "worksheets": [
                {"name": "Sheet1", "mark_type": "Bar"},
                {"name": "Sheet2", "mark_type": "Line"},
                {"name": "Sheet3", "mark_type": "Text"},
            ],
        }
        result = json.loads(filter_metadata_for_page(report_input, page))
        ws_names = [w["name"] for w in result["worksheets"]]
        self.assertEqual(ws_names, ["Sheet1"])
        self.assertEqual(result["datasource_index"], {"fed.1": "DS1"})

    def test_empty_page_returns_no_worksheets(self):
        from Tableau2PowerBI.agents.report_skeleton import SkeletonPage

        page = SkeletonPage(
            dashboard_name="Empty",
            display_name="Empty",
            hex_id="c1c2c3c4c5c6c7c8c9c0",
            height=720,
            visuals=[],
        )
        result = json.loads(filter_metadata_for_page({"worksheets": [{"name": "X"}]}, page))
        self.assertEqual(result["worksheets"], [])

    def test_tdd_format_extracts_visuals_from_pages(self):
        """TDD pages[].visuals[] format is correctly filtered."""
        from Tableau2PowerBI.agents.report_skeleton import SkeletonPage, SkeletonVisual, VisualPosition

        page = SkeletonPage(
            dashboard_name="Clienti",
            display_name="Clienti",
            hex_id="a1b2c3d4e5f6a7b8c9d0",
            height=720,
            visuals=[
                SkeletonVisual(
                    worksheet_name="Slicer — Categoria",
                    visual_type="slicer",
                    hex_id="b1b2c3d4e5f6a7b8c9d0",
                    position=VisualPosition(x=0, y=0, width=220, height=40, tab_order=0),
                ),
            ],
        )
        report_input = {
            "pages": [
                {
                    "dashboard_name": "Clienti",
                    "display_name": "Clienti",
                    "visuals": [
                        {
                            "worksheet_name": "Slicer — Categoria",
                            "visual_type": "slicer",
                            "field_bindings": [
                                {
                                    "pbi_table": "Ordini",
                                    "pbi_field": "Categoria",
                                    "field_kind": "Column",
                                    "aggregation": "none",
                                    "well": "Category",
                                },
                            ],
                        },
                        {
                            "worksheet_name": "Scatter",
                            "visual_type": "scatterChart",
                            "field_bindings": [],
                        },
                    ],
                },
            ],
            "entity_resolution": {"calculated_field_map": {}},
        }
        result = json.loads(filter_metadata_for_page(report_input, page))
        self.assertEqual(len(result["visuals"]), 1)
        self.assertEqual(result["visuals"][0]["worksheet_name"], "Slicer — Categoria")
        self.assertIn("entity_resolution", result)
        self.assertNotIn("worksheets", result)


class GenerateStaticFilesTests(unittest.TestCase):
    """Tests for deterministic PBIR boilerplate generation."""

    @classmethod
    def setUpClass(cls):
        from Tableau2PowerBI.agents.report_skeleton import ReportSkeleton, SkeletonPage, SkeletonVisual, VisualPosition

        cls.skeleton = ReportSkeleton(
            pages=[
                SkeletonPage(
                    dashboard_name="Panoramica",
                    display_name="Panoramica",
                    hex_id="aaaaaaaaaaaaaaaaaaa1",
                    height=900,
                    visuals=[
                        SkeletonVisual(
                            worksheet_name="Vendite",
                            visual_type="barChart",
                            hex_id="bbbbbbbbbbbbbbbbbb01",
                            position=VisualPosition(x=0, y=0, width=600, height=400, tab_order=0),
                        ),
                    ],
                ),
                SkeletonPage(
                    dashboard_name="Clienti",
                    display_name="Clienti",
                    hex_id="aaaaaaaaaaaaaaaaaaa2",
                    height=720,
                    visuals=[],
                ),
            ],
        )
        cls.files = generate_static_files(cls.skeleton, "Test")

    def test_platform_file_present(self):
        self.assertIn("Test.Report/.platform", self.files)

    def test_definition_pbir_present(self):
        self.assertIn("Test.Report/definition.pbir", self.files)
        content = json.loads(self.files["Test.Report/definition.pbir"])
        self.assertEqual(content["version"], "4.0")
        self.assertIn("Test.SemanticModel", content["datasetReference"]["byPath"]["path"])

    def test_local_settings_present(self):
        self.assertIn("Test.Report/.pbi/localSettings.json", self.files)

    def test_version_json_present(self):
        path = "Test.Report/definition/version.json"
        self.assertIn(path, self.files)
        content = json.loads(self.files[path])
        self.assertEqual(content["version"], "2.0.0")

    def test_report_json_has_correct_structure(self):
        path = "Test.Report/definition/report.json"
        self.assertIn(path, self.files)
        content = json.loads(self.files[path])
        self.assertNotIn("layoutOptimization", content)
        rvi = content["themeCollection"]["baseTheme"]["reportVersionAtImport"]
        self.assertIsInstance(rvi, dict)
        self.assertIn("visual", rvi)

    def test_pages_json_has_correct_order(self):
        path = "Test.Report/definition/pages/pages.json"
        self.assertIn(path, self.files)
        content = json.loads(self.files[path])
        self.assertEqual(content["pageOrder"], ["aaaaaaaaaaaaaaaaaaa1", "aaaaaaaaaaaaaaaaaaa2"])
        self.assertEqual(content["activePageName"], "aaaaaaaaaaaaaaaaaaa1")

    def test_page_json_per_page(self):
        for page in self.skeleton.pages:
            path = f"Test.Report/definition/pages/{page.hex_id}/page.json"
            self.assertIn(path, self.files)
            content = json.loads(self.files[path])
            self.assertEqual(content["name"], page.hex_id)
            self.assertEqual(content["displayName"], page.display_name)
            self.assertEqual(content["displayOption"], "FitToPage")

    def test_bookmark_per_page(self):
        for page in self.skeleton.pages:
            path = f"Test.Report/definition/bookmarks/bookmark_{page.hex_id}.json"
            self.assertIn(path, self.files)
            content = json.loads(self.files[path])
            self.assertEqual(content["id"], f"bookmark_{page.hex_id}")

    def test_platform_has_valid_guid(self):
        content = json.loads(self.files["Test.Report/.platform"])
        guid = content["config"]["logicalId"]
        self.assertRegex(guid, r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class AssembleReportTests(unittest.TestCase):
    """Tests for merging skeleton + page visuals into PbirReportDecisions."""

    def test_merges_visuals_into_correct_paths(self):
        from Tableau2PowerBI.agents.report_page_visuals import PageVisualsOutput
        from Tableau2PowerBI.agents.report_skeleton import ReportSkeleton, SkeletonPage, SkeletonVisual, VisualPosition

        skeleton = ReportSkeleton(
            pages=[
                SkeletonPage(
                    dashboard_name="Dash",
                    display_name="Dash",
                    hex_id="aaaaaaaaaaaaaaaaaaa1",
                    height=720,
                    visuals=[
                        SkeletonVisual(
                            worksheet_name="Sheet1",
                            visual_type="barChart",
                            hex_id="bbbbbbbbbbbbbbbbbb01",
                            position=VisualPosition(x=0, y=0, width=400, height=300, tab_order=0),
                        ),
                    ],
                ),
            ],
        )
        page_visuals = {
            "aaaaaaaaaaaaaaaaaaa1": PageVisualsOutput(visuals={"bbbbbbbbbbbbbbbbbb01": '{"visual": "content"}'}),
        }
        static_files = generate_static_files(skeleton, "WB")
        files, warnings = assemble_report(skeleton, page_visuals, "WB", static_files)
        expected_path = "WB.Report/definition/pages/aaaaaaaaaaaaaaaaaaa1/visuals/bbbbbbbbbbbbbbbbbb01/visual.json"
        self.assertIn(expected_path, files)
        self.assertEqual(files[expected_path], '{"visual": "content"}')

    def test_missing_page_output_skipped(self):
        from Tableau2PowerBI.agents.report_skeleton import ReportSkeleton, SkeletonPage

        skeleton = ReportSkeleton(
            pages=[
                SkeletonPage(
                    dashboard_name="Dash",
                    display_name="Dash",
                    hex_id="aaaaaaaaaaaaaaaaaaa1",
                    height=720,
                    visuals=[],
                ),
            ],
        )
        static_files = generate_static_files(skeleton, "WB")
        files, _ = assemble_report(skeleton, {}, "WB", static_files)
        self.assertIn("WB.Report/.platform", files)
        self.assertIn("WB.Report/definition/pages/pages.json", files)

    def test_warnings_merged_from_all_sources(self):
        from Tableau2PowerBI.agents.report_page_visuals import PageVisualsOutput
        from Tableau2PowerBI.agents.report_skeleton import ReportSkeleton, SkeletonPage, SkeletonVisual, VisualPosition

        skeleton = ReportSkeleton(
            pages=[
                SkeletonPage(
                    dashboard_name="D",
                    display_name="D",
                    hex_id="aaaaaaaaaaaaaaaaaaa1",
                    height=720,
                    visuals=[
                        SkeletonVisual(
                            worksheet_name="S",
                            visual_type="barChart",
                            hex_id="bbbbbbbbbbbbbbbbbb01",
                            position=VisualPosition(x=0, y=0, width=400, height=300, tab_order=0),
                        ),
                    ],
                ),
            ],
            warnings=[
                MigrationWarning(
                    severity="WARN",
                    code="SKEL_W",
                    message="skel",
                    timestamp="2026-01-01T00:00:00Z",
                ),
            ],
        )
        page_visuals = {
            "aaaaaaaaaaaaaaaaaaa1": PageVisualsOutput(
                visuals={"bbbbbbbbbbbbbbbbbb01": "{}"},
                warnings=[
                    MigrationWarning(
                        severity="WARN",
                        code="PAGE_W",
                        message="page",
                        timestamp="2026-01-01T00:00:00Z",
                    ),
                ],
            ),
        }
        static_files = generate_static_files(skeleton, "WB")
        _, warnings = assemble_report(skeleton, page_visuals, "WB", static_files)
        codes = [w.code for w in warnings]
        self.assertIn("SKEL_W", codes)
        self.assertIn("PAGE_W", codes)


class BuildSkeletonFromTddTests(unittest.TestCase):
    """Tests for deterministic skeleton construction from TDD data."""

    def _sample_tdd(self) -> dict:
        return {
            "pages": [
                {
                    "dashboard_name": "Clienti",
                    "display_name": "Clienti",
                    "page_order": 0,
                    "width": 1280,
                    "height": 720,
                    "visuals": [
                        {
                            "worksheet_name": "Slicer — Categoria",
                            "visual_type": "slicer",
                            "position": {"x": 24, "y": 5, "width": 220, "height": 40},
                        },
                        {
                            "worksheet_name": "Dispersione cliente",
                            "visual_type": "scatterChart",
                            "position": {"x": 5, "y": 160, "width": 566, "height": 554},
                        },
                    ],
                },
                {
                    "dashboard_name": "Panoramica",
                    "display_name": "Panoramica",
                    "page_order": 1,
                    "width": 1280,
                    "height": 720,
                    "visuals": [
                        {
                            "worksheet_name": "Vendite totali",
                            "visual_type": "barChart",
                            "position": {"x": 0, "y": 0, "width": 600, "height": 400},
                        },
                    ],
                },
            ],
            "standalone_worksheets": ["Previsione", "Prestazioni"],
            "entity_resolution": {},
        }

    def test_creates_correct_page_count(self):
        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        self.assertEqual(len(skeleton.pages), 4)

    def test_page_display_names(self):
        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        names = [p.display_name for p in skeleton.pages]
        self.assertEqual(names, ["Clienti", "Panoramica", "Previsione", "Prestazioni"])

    def test_visual_count_per_page(self):
        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        self.assertEqual(len(skeleton.pages[0].visuals), 2)
        self.assertEqual(len(skeleton.pages[1].visuals), 1)

    def test_visual_types_preserved(self):
        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        types = [v.visual_type for v in skeleton.pages[0].visuals]
        self.assertEqual(types, ["slicer", "scatterChart"])

    def test_visual_positions_mapped(self):
        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        pos = skeleton.pages[0].visuals[0].position
        self.assertEqual(pos.x, 24)
        self.assertEqual(pos.y, 5)
        self.assertEqual(pos.width, 220)
        self.assertEqual(pos.height, 40)

    def test_hex_ids_are_20_char_hex(self):
        import re

        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        hex_re = re.compile(r"^[0-9a-f]{20}$")
        for page in skeleton.pages:
            self.assertRegex(page.hex_id, hex_re)
            for visual in page.visuals:
                self.assertRegex(visual.hex_id, hex_re)

    def test_hex_ids_deterministic(self):
        s1 = build_skeleton_from_tdd(self._sample_tdd())
        s2 = build_skeleton_from_tdd(self._sample_tdd())
        self.assertEqual(s1.pages[0].hex_id, s2.pages[0].hex_id)
        self.assertEqual(s1.pages[0].visuals[0].hex_id, s2.pages[0].visuals[0].hex_id)

    def test_hex_ids_unique(self):
        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        all_ids = [p.hex_id for p in skeleton.pages]
        for page in skeleton.pages:
            all_ids.extend(v.hex_id for v in page.visuals)
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_page_height_expanded_for_visuals(self):
        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        self.assertEqual(skeleton.pages[0].height, 720)

    def test_page_height_expanded_when_visual_overflows(self):
        tdd = {
            "pages": [
                {
                    "dashboard_name": "Tall",
                    "display_name": "Tall",
                    "width": 1280,
                    "height": 720,
                    "visuals": [
                        {
                            "worksheet_name": "WS",
                            "visual_type": "barChart",
                            "position": {"x": 0, "y": 600, "width": 400, "height": 300},
                        },
                    ],
                },
            ],
        }
        skeleton = build_skeleton_from_tdd(tdd)
        self.assertEqual(skeleton.pages[0].height, 900)

    def test_orphaned_worksheets_become_pages(self):
        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        self.assertEqual(len(skeleton.warnings), 0)

        standalone_pages = skeleton.pages[2:]
        self.assertEqual([p.display_name for p in standalone_pages], ["Previsione", "Prestazioni"])
        self.assertEqual([len(p.visuals) for p in standalone_pages], [1, 1])
        self.assertEqual([p.visuals[0].visual_type for p in standalone_pages], ["tableEx", "tableEx"])

    def test_orphaned_worksheet_with_locale_characters_is_migrated(self):
        tdd = self._sample_tdd()
        tdd["standalone_worksheets"] = ["Informazioni: Rapporto profitto per città"]

        skeleton = build_skeleton_from_tdd(tdd)
        locale_page = skeleton.pages[-1]

        self.assertEqual(locale_page.display_name, "Informazioni: Rapporto profitto per città")
        self.assertEqual(locale_page.visuals[0].worksheet_name, "Informazioni: Rapporto profitto per città")

    def test_tab_order_assigned_sequentially(self):
        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        orders = [v.position.tab_order for v in skeleton.pages[0].visuals]
        self.assertEqual(orders, [0, 1])

    def test_empty_pages_list(self):
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            build_skeleton_from_tdd({"pages": []})

    def test_worksheet_names_preserved(self):
        skeleton = build_skeleton_from_tdd(self._sample_tdd())
        ws_names = [v.worksheet_name for v in skeleton.pages[0].visuals]
        self.assertEqual(ws_names, ["Slicer — Categoria", "Dispersione cliente"])
