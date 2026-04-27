"""Field-reference and schema tests for the PBIR report visuals agent."""

import json
import logging
import unittest

from Tableau2PowerBI.agents.report_visuals import (
    PbirReportDecisions,
    PbirReportGeneratorAgent,
)
from Tableau2PowerBI.agents.report_visuals.pipeline_inputs import build_schema_from_tdd_sections
from Tableau2PowerBI.agents.report_visuals.postprocessing import (
    build_field_index_from_tdd,
    fix_field_references,
)
from Tableau2PowerBI.core.config import AgentSettings

VISUAL_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/" "definition/visualContainer/2.7.0/schema.json"
)
_TEST_LOGGER = logging.getLogger("test.pbir_visuals")


def _build_agent() -> PbirReportGeneratorAgent:
    """Construct a PbirReportGeneratorAgent without Azure dependencies."""
    agent = object.__new__(PbirReportGeneratorAgent)
    agent.skill_name = "pbir_report_generator_agent"
    agent.settings = AgentSettings(project_endpoint="https://example.test")
    agent.logger = logging.getLogger("test.pbir_visuals")
    return agent


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


_VIS_PATH = "WB.Report/definition/pages/aaa/visuals/v1/visual.json"


class FixFieldReferencesTests(unittest.TestCase):
    """Tests for the _fix_field_references post-processing step."""

    def test_resolves_calculation_name_to_pbi_measure(self):
        """Calculation_XXX in Property is replaced with the PBI measure name."""
        visual = _make_visual_json("Ordini", "Calculation_9921103144103743")
        decisions = PbirReportDecisions(files={_VIS_PATH: visual})

        out_files, metrics = fix_field_references(
            decisions.files,
            calc_mapping={"Calculation_9921103144103743": "Rapporto profitto"},
            measure_set={"Ordini.Rapporto profitto"},
            column_set=set(),
            logger=_TEST_LOGGER,
        )
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)
        self.assertEqual(metrics["calc_names_resolved"], 1)

        out = json.loads(result.files[_VIS_PATH])
        proj = out["visual"]["query"]["queryState"]["Values"]["projections"][0]
        self.assertEqual(proj["field"]["Measure"]["Property"], "Rapporto profitto")
        self.assertEqual(proj["queryRef"], "Ordini.Rapporto profitto")
        self.assertEqual(proj["nativeQueryRef"], "Rapporto profitto")

    def test_fixes_measure_to_column(self):
        """A field referenced as Measure but actually a Column is corrected."""
        visual = _make_visual_json("Ordini", "Profitto", kind="Measure")
        decisions = PbirReportDecisions(files={_VIS_PATH: visual})

        out_files, metrics = fix_field_references(
            decisions.files,
            calc_mapping={},
            measure_set=set(),
            column_set={"Ordini.Profitto"},
            logger=_TEST_LOGGER,
        )
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)
        self.assertEqual(metrics["field_kinds_fixed"], 1)

        out = json.loads(result.files[_VIS_PATH])
        proj = out["visual"]["query"]["queryState"]["Values"]["projections"][0]
        self.assertIn("Column", proj["field"])
        self.assertNotIn("Measure", proj["field"])
        self.assertEqual(proj["field"]["Column"]["Property"], "Profitto")

    def test_fixes_column_to_measure(self):
        """A field referenced as Column but actually a Measure is corrected."""
        visual = _make_visual_json("Ordini", "Rapporto profitto", kind="Column")
        decisions = PbirReportDecisions(files={_VIS_PATH: visual})

        out_files, _ = fix_field_references(
            decisions.files,
            calc_mapping={},
            measure_set={"Ordini.Rapporto profitto"},
            column_set=set(),
            logger=_TEST_LOGGER,
        )
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[_VIS_PATH])
        proj = out["visual"]["query"]["queryState"]["Values"]["projections"][0]
        self.assertIn("Measure", proj["field"])
        self.assertNotIn("Column", proj["field"])

    def test_leaves_correct_references_unchanged(self):
        """Fields already referencing the correct kind are left alone."""
        visual = _make_visual_json("Ordini", "Vendite", kind="Column")
        decisions = PbirReportDecisions(files={_VIS_PATH: visual})

        out_files, _ = fix_field_references(
            decisions.files,
            calc_mapping={},
            measure_set=set(),
            column_set={"Ordini.Vendite"},
            logger=_TEST_LOGGER,
        )
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[_VIS_PATH])
        proj = out["visual"]["query"]["queryState"]["Values"]["projections"][0]
        self.assertIn("Column", proj["field"])
        self.assertEqual(proj["field"]["Column"]["Property"], "Vendite")

    def test_fixes_filter_config_references(self):
        """filterConfig.filters entries are also corrected."""
        visual = _make_visual_json("Ordini", "Calculation_9921103144103743")
        decisions = PbirReportDecisions(files={_VIS_PATH: visual})

        out_files, _ = fix_field_references(
            decisions.files,
            calc_mapping={"Calculation_9921103144103743": "Rapporto profitto"},
            measure_set={"Ordini.Rapporto profitto"},
            column_set=set(),
            logger=_TEST_LOGGER,
        )
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[_VIS_PATH])
        filt = out["filterConfig"]["filters"][0]
        self.assertEqual(filt["field"]["Measure"]["Property"], "Rapporto profitto")

    def test_non_visual_files_untouched(self):
        """Files that aren't visual.json are passed through unchanged."""
        decisions = PbirReportDecisions(
            files={
                "WB.Report/.platform": '{"meta": "data"}',
                _VIS_PATH: _make_visual_json("Ordini", "Vendite", kind="Column"),
            }
        )

        out_files, _ = fix_field_references(
            decisions.files,
            calc_mapping={},
            measure_set=set(),
            column_set={"Ordini.Vendite"},
            logger=_TEST_LOGGER,
        )
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        self.assertEqual(result.files["WB.Report/.platform"], '{"meta": "data"}')

    def test_unknown_field_left_as_is(self):
        """Fields not in any lookup are left unchanged (no crash)."""
        visual = _make_visual_json("Ordini", "UnknownField", kind="Measure")
        decisions = PbirReportDecisions(files={_VIS_PATH: visual})

        out_files, _ = fix_field_references(
            decisions.files,
            calc_mapping={},
            measure_set=set(),
            column_set=set(),
            logger=_TEST_LOGGER,
        )
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[_VIS_PATH])
        proj = out["visual"]["query"]["queryState"]["Values"]["projections"][0]
        self.assertEqual(proj["field"]["Measure"]["Property"], "UnknownField")

    def test_calc_resolved_and_kind_fixed_in_same_pass(self):
        """Both calc resolution and kind fix happen for the same field."""
        visual = _make_visual_json(
            "Ordini",
            "Calculation_9921103144103743",
            kind="Column",
        )
        decisions = PbirReportDecisions(files={_VIS_PATH: visual})

        out_files, metrics = fix_field_references(
            decisions.files,
            calc_mapping={"Calculation_9921103144103743": "Rapporto profitto"},
            measure_set={"Ordini.Rapporto profitto"},
            column_set=set(),
            logger=_TEST_LOGGER,
        )
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[_VIS_PATH])
        proj = out["visual"]["query"]["queryState"]["Values"]["projections"][0]
        self.assertIn("Measure", proj["field"])
        self.assertNotIn("Column", proj["field"])
        self.assertEqual(proj["field"]["Measure"]["Property"], "Rapporto profitto")
        self.assertEqual(proj["queryRef"], "Ordini.Rapporto profitto")

    def test_aggregation_kind_left_unchanged(self):
        """Aggregation field kind is preserved (valid PBIR for aggregated columns)."""
        visual = json.dumps(
            {
                "$schema": VISUAL_SCHEMA,
                "name": "vis01",
                "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300},
                "visual": {
                    "visualType": "barChart",
                    "query": {
                        "queryState": {
                            "Values": {
                                "projections": [
                                    {
                                        "field": {
                                            "Aggregation": {
                                                "Expression": {
                                                    "Column": {
                                                        "Expression": {"SourceRef": {"Entity": "Table"}},
                                                        "Property": "quanto",
                                                    }
                                                },
                                                "Function": 0,
                                            }
                                        },
                                        "queryRef": "Sum(Table.quanto)",
                                        "nativeQueryRef": "Sum of quanto",
                                    }
                                ]
                            }
                        }
                    },
                    "drillFilterOtherVisuals": True,
                },
                "filterConfig": {"filters": []},
            }
        )
        decisions = PbirReportDecisions(files={_VIS_PATH: visual})

        out_files, metrics = fix_field_references(
            decisions.files,
            calc_mapping={},
            measure_set=set(),
            column_set={"Table.quanto"},
            logger=_TEST_LOGGER,
        )
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[_VIS_PATH])
        proj = out["visual"]["query"]["queryState"]["Values"]["projections"][0]
        self.assertIn("Aggregation", proj["field"])
        self.assertNotIn("Column", proj["field"])
        self.assertNotIn("Measure", proj["field"])
        self.assertEqual(metrics["field_kinds_fixed"], 0)

    def test_aggregation_filter_left_unchanged(self):
        """Aggregation in filterConfig.filters is preserved."""
        visual = json.dumps(
            {
                "$schema": VISUAL_SCHEMA,
                "name": "vis01",
                "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300},
                "visual": {
                    "visualType": "barChart",
                    "query": {"queryState": {}},
                    "drillFilterOtherVisuals": True,
                },
                "filterConfig": {
                    "filters": [
                        {
                            "name": "f1",
                            "field": {
                                "Aggregation": {
                                    "Expression": {
                                        "Column": {
                                            "Expression": {"SourceRef": {"Entity": "Table"}},
                                            "Property": "quanto",
                                        }
                                    },
                                    "Function": 0,
                                }
                            },
                            "type": "Advanced",
                        }
                    ]
                },
            }
        )
        decisions = PbirReportDecisions(files={_VIS_PATH: visual})

        out_files, _ = fix_field_references(
            decisions.files,
            calc_mapping={},
            measure_set=set(),
            column_set={"Table.quanto"},
            logger=_TEST_LOGGER,
        )
        result = PbirReportDecisions(files=out_files, warnings=decisions.warnings)

        out = json.loads(result.files[_VIS_PATH])
        filt = out["filterConfig"]["filters"][0]
        self.assertIn("Aggregation", filt["field"])
        self.assertNotIn("Column", filt["field"])


class BuildFieldIndexFromTddTests(unittest.TestCase):
    """Tests for the TDD-based field index builder."""

    def test_builds_measures_from_tdd(self):
        tdd_sm = {"tables": [{"name": "Ordini", "columns": [{"name": "Vendite"}]}]}
        tdd_dax = {
            "measures": [
                {"owner_table": "Ordini", "caption": "Total Sales"},
            ]
        }
        tdd_report = {"entity_resolution": {"calculated_field_map": {}}}
        calc_map, measure_set, column_set = build_field_index_from_tdd(
            tdd_sm,
            tdd_dax,
            tdd_report,
        )
        self.assertIn("Ordini.Total Sales", measure_set)
        self.assertIn("Ordini.Vendite", column_set)
        self.assertEqual(calc_map, {})

    def test_builds_calc_mapping_from_tdd(self):
        tdd_report = {
            "entity_resolution": {
                "calculated_field_map": {
                    "Calculation_123": "My Measure",
                }
            }
        }
        calc_map, _, _ = build_field_index_from_tdd({}, {}, tdd_report)
        self.assertEqual(calc_map, {"Calculation_123": "My Measure"})

    def test_empty_tdd_returns_empty_sets(self):
        calc_map, measure_set, column_set = build_field_index_from_tdd({}, {}, {})
        self.assertEqual(calc_map, {})
        self.assertEqual(measure_set, set())
        self.assertEqual(column_set, set())


class BuildSchemaFromTddTests(unittest.TestCase):
    """Tests for TDD-based schema builder."""

    def test_schema_includes_tables_and_columns(self):
        tdd_sm = {
            "tables": [
                {"name": "Ordini", "columns": [{"name": "Vendite"}, {"name": "ID"}]},
            ]
        }
        result = build_schema_from_tdd_sections(tdd_sm, {}, {})
        self.assertIn("Ordini", result)
        self.assertIn("Vendite", result)
        self.assertIn("ID", result)

    def test_schema_includes_measures(self):
        tdd_sm = {"tables": [{"name": "Ordini", "columns": []}]}
        tdd_dax = {
            "measures": [
                {"owner_table": "Ordini", "caption": "Total Sales"},
            ]
        }
        result = build_schema_from_tdd_sections(tdd_sm, tdd_dax, {})
        self.assertIn("Total Sales", result)

    def test_schema_includes_calc_mapping(self):
        tdd_report = {
            "entity_resolution": {
                "calculated_field_map": {"Calculation_123": "My Measure"},
            }
        }
        result = build_schema_from_tdd_sections({}, {}, tdd_report)
        self.assertIn("Calculation_123", result)
        self.assertIn("My Measure", result)
