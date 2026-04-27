"""Tests for report_visuals.pipeline_inputs — TDD loading and schema building."""

from __future__ import annotations

import json
import logging
import unittest

from Tableau2PowerBI.agents.report_visuals.pipeline_inputs import (
    build_schema_from_tdd_sections,
    load_tdd_sections,
)
from Tableau2PowerBI.core.config import AgentSettings
from tests.support import managed_tempdir

# ── build_schema_from_tdd_sections ───────────────────────────────────


class BuildSchemaFromTddSectionsTests(unittest.TestCase):
    """Tests for the deterministic schema builder."""

    def test_includes_table_and_column_names(self):
        tdd_sm = {
            "tables": [
                {"name": "Orders", "columns": [{"name": "OrderID"}, {"name": "Amount"}]},
            ],
        }
        result = build_schema_from_tdd_sections(tdd_sm, {}, {})
        self.assertIn("Orders", result)
        self.assertIn("OrderID", result)
        self.assertIn("Amount", result)

    def test_includes_measures(self):
        tdd_sm = {
            "tables": [{"name": "Sales", "columns": [{"name": "Revenue"}]}],
        }
        tdd_dax = {
            "measures": [
                {"owner_table": "Sales", "caption": "Total Revenue"},
            ],
        }
        result = build_schema_from_tdd_sections(tdd_sm, tdd_dax, {})
        self.assertIn("Total Revenue", result)

    def test_measures_without_matching_table_listed_separately(self):
        tdd_sm = {"tables": []}
        tdd_dax = {
            "measures": [
                {"owner_table": "Orphan", "caption": "Measure1"},
            ],
        }
        result = build_schema_from_tdd_sections(tdd_sm, tdd_dax, {})
        self.assertIn("Orphan", result)
        self.assertIn("(no columns)", result)
        self.assertIn("Measure1", result)

    def test_includes_calc_mapping(self):
        tdd_report = {
            "entity_resolution": {
                "calculated_field_map": {
                    "Calculation_123": "Total Sales",
                },
            },
        }
        result = build_schema_from_tdd_sections({}, {}, tdd_report)
        self.assertIn("Calculation_123", result)
        self.assertIn("Total Sales", result)

    def test_empty_tdd_returns_header_only(self):
        result = build_schema_from_tdd_sections({}, {}, {})
        self.assertIn("Power BI table and column names", result)
        # Should have no table entries
        self.assertNotIn("  - ", result)

    def test_table_with_no_columns_shows_placeholder(self):
        tdd_sm = {
            "tables": [{"name": "EmptyTable", "columns": []}],
        }
        result = build_schema_from_tdd_sections(tdd_sm, {}, {})
        self.assertIn("EmptyTable", result)
        self.assertIn("(no columns)", result)

    def test_table_with_no_measures_shows_placeholder(self):
        tdd_sm = {
            "tables": [{"name": "T1", "columns": [{"name": "C1"}]}],
        }
        result = build_schema_from_tdd_sections(tdd_sm, {}, {})
        self.assertIn("(no measures)", result)

    def test_multiple_tables_all_present(self):
        tdd_sm = {
            "tables": [
                {"name": "A", "columns": [{"name": "A1"}]},
                {"name": "B", "columns": [{"name": "B1"}, {"name": "B2"}]},
            ],
        }
        result = build_schema_from_tdd_sections(tdd_sm, {}, {})
        self.assertIn("A", result)
        self.assertIn("B", result)
        self.assertIn("B1, B2", result)


# ── load_tdd_sections ────────────────────────────────────────────────


class LoadTddSectionsTests(unittest.TestCase):
    """Tests for TDD file loading."""

    def _logger(self) -> logging.Logger:
        return logging.getLogger("test.pipeline_inputs")

    def test_loads_all_three_sections(self):
        with managed_tempdir() as tmpdir:
            tdd_dir = tmpdir / "target_technical_doc_agent" / "TestWb"
            tdd_dir.mkdir(parents=True)

            (tdd_dir / "report_design.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
            (tdd_dir / "semantic_model_design.json").write_text(json.dumps({"tables": []}), encoding="utf-8")
            (tdd_dir / "dax_measures_design.json").write_text(json.dumps({"measures": []}), encoding="utf-8")

            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            report, sm, dax = load_tdd_sections("TestWb", settings, self._logger())
            self.assertEqual(report, {"pages": []})
            self.assertEqual(sm, {"tables": []})
            self.assertEqual(dax, {"measures": []})

    def test_dax_optional_returns_empty_dict(self):
        with managed_tempdir() as tmpdir:
            tdd_dir = tmpdir / "target_technical_doc_agent" / "TestWb"
            tdd_dir.mkdir(parents=True)

            (tdd_dir / "report_design.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
            (tdd_dir / "semantic_model_design.json").write_text(json.dumps({"tables": []}), encoding="utf-8")
            # No dax_measures_design.json

            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            _, _, dax = load_tdd_sections("TestWb", settings, self._logger())
            self.assertEqual(dax, {})

    def test_raises_when_report_design_missing(self):
        with managed_tempdir() as tmpdir:
            tdd_dir = tmpdir / "target_technical_doc_agent" / "TestWb"
            tdd_dir.mkdir(parents=True)

            (tdd_dir / "semantic_model_design.json").write_text(json.dumps({"tables": []}), encoding="utf-8")

            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            with self.assertRaises(FileNotFoundError):
                load_tdd_sections("TestWb", settings, self._logger())

    def test_raises_when_semantic_model_design_missing(self):
        with managed_tempdir() as tmpdir:
            tdd_dir = tmpdir / "target_technical_doc_agent" / "TestWb"
            tdd_dir.mkdir(parents=True)

            (tdd_dir / "report_design.json").write_text(json.dumps({"pages": []}), encoding="utf-8")

            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            with self.assertRaises(FileNotFoundError):
                load_tdd_sections("TestWb", settings, self._logger())
