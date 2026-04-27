import json
import unittest
from pathlib import Path

from Tableau2PowerBI.agents.metadata_extractor.downstream_payloads import (
    FUNCTIONAL_DOC_INPUT_SLIM_FILENAME,
    build_all_payload_files,
    build_connections_input,
    build_functional_doc_input_slim,
    build_report_input,
    build_semantic_model_input,
)
from tests.support import managed_tempdir


class DownstreamPayloadsTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {
            "datasources": [
                {
                    "name": "Sales",
                    "caption": "Sales Caption",
                    "connection": {"type": "excel-direct"},
                    "tables": [{"name": "Orders", "physical_table": "[Orders$]"}],
                    "joins": [{"join_type": "inner"}],
                    "relationships": [{"left_table": "Orders", "right_table": "Customers"}],
                    "col_mapping": [{"logical_field": "[Id]", "physical_column": "[Orders].[Id]"}],
                    "columns": [
                        {"name": "[:TableauInternal]"},
                        {"name": "[Sales]", "role": "measure"},
                    ],
                    "calculated_fields": [{"name": "[Profit]"}],
                    "groups": [{"name": "Keep", "members": ["A"]}, {"name": "Drop", "members": []}],
                    "sets": [],
                    "metadata_records": [
                        {
                            "class": "column",
                            "local_name": "Sales",
                            "local_type": "real",
                            "remote_name": "SalesRemote",
                            "remote_type": "float",
                            "aggregation": "sum",
                            "nullable": "true",
                        }
                    ],
                },
                {
                    "name": "Sales",
                    "caption": "Duplicate Caption",
                    "columns": [],
                    "calculated_fields": [],
                    "metadata_records": [],
                },
            ],
            "worksheets": [
                {
                    "name": "Sheet 1",
                    "cols_shelf": [{"field": "Sales", "raw": "[Sales]"}],
                    "rows_shelf": [],
                    "filters": [],
                }
            ],
            "dashboards": [
                {
                    "name": "Dashboard 1",
                    "size": {"width": "100"},
                    "sheets": ["Sheet 1"],
                    "layout_zones": [{"name": "Sheet 1", "x": "0", "y": "0", "w": "100", "h": "100"}],
                }
            ],
            "actions": [{"name": "Action 1", "type": "filter", "source_sheet": "Sheet 1"}],
            "parameters": [{"name": "[Param]", "default_value": "'Default'"}],
        }
        self.prepared_datasources = [self.metadata["datasources"][0]]

    def test_build_semantic_model_input_filters_and_shapes_explicitly(self):
        payload = build_semantic_model_input(self.metadata, self.prepared_datasources)

        datasource = payload["datasources"][0]
        self.assertEqual(datasource["name"], "Sales Caption")
        self.assertEqual(datasource["columns"], [{"name": "[Sales]", "role": "measure"}])
        self.assertEqual(datasource["groups"], [{"name": "Keep", "members": ["A"]}])
        self.assertEqual(
            datasource["physical_columns"],
            [
                {
                    "local_name": "Sales",
                    "local_type": "real",
                    "remote_name": "SalesRemote",
                }
            ],
        )

    def test_build_semantic_model_input_strips_resolved_filename(self):
        """resolved_filename is an implementation detail — must not reach the LLM prompt."""
        datasources = [
            {
                **self.prepared_datasources[0],
                "connection": {
                    "type": "excel-direct",
                    "filename": "Data/Sales.xlsx",
                    "resolved_filename": "C:\\abs\\path\\Data\\Sales.xlsx",
                    "relative_path": "Data/Sales.xlsx",
                },
            }
        ]
        payload = build_semantic_model_input(self.metadata, datasources)

        connection = payload["datasources"][0]["connection"]
        self.assertNotIn("resolved_filename", connection)
        self.assertIn("relative_path", connection)
        self.assertEqual(connection["relative_path"], "Data/Sales.xlsx")

    def test_build_report_input_strips_raw_fields(self):
        payload = build_report_input(self.metadata, self.prepared_datasources)

        self.assertEqual(payload["datasource_index"], {"Sales": "Sales Caption"})
        self.assertEqual(payload["worksheets"][0]["cols_shelf"], [{"field": "Sales"}])
        self.assertNotIn("raw", json.dumps(payload))
        # layout_zones are included in the dashboard entry.
        self.assertEqual(
            payload["dashboards"][0]["layout_zones"],
            [{"name": "Sheet 1", "x": "0", "y": "0", "w": "100", "h": "100"}],
        )
        # datasources with calculated_fields are included at top level.
        self.assertEqual(payload["datasources"][0]["name"], "Sales")
        self.assertEqual(payload["datasources"][0]["calculated_fields"], [{"name": "[Profit]"}])

    def test_build_report_input_omits_datasources_without_calc_fields(self):
        """Datasources without calculated_fields are excluded from the output."""
        ds_no_calcs = {
            "name": "NoCalcs",
            "caption": "NoCalcs Caption",
            "columns": [{"name": "[Col1]"}],
            "metadata_records": [{"class": "column", "local_name": "Col1", "local_type": "string"}],
        }
        payload = build_report_input(self.metadata, [ds_no_calcs])

        self.assertNotIn("datasources", payload)

    def test_build_report_input_omits_layout_zones_when_absent(self):
        """Dashboards with no layout_zones key should not have layout_zones in output."""
        metadata = dict(self.metadata)
        metadata["dashboards"] = [{"name": "Dashboard 1", "size": {"width": "100"}, "sheets": ["Sheet 1"]}]

        payload = build_report_input(metadata, self.prepared_datasources)

        self.assertNotIn("layout_zones", payload["dashboards"][0])

    def test_build_report_input_drops_empty_actions(self):
        metadata = dict(self.metadata)
        metadata["actions"] = [{"name": None, "type": None, "source_sheet": None}]

        payload = build_report_input(metadata, self.prepared_datasources)

        self.assertNotIn("actions", payload)

    def test_build_connections_input_uses_prepared_datasources_once(self):
        payload = build_connections_input(self.metadata, self.prepared_datasources)

        self.assertEqual(
            payload,
            {
                "datasources": [
                    {
                        "name": "Sales Caption",
                        "connection": {"type": "excel-direct"},
                        "physical_tables": ["[Orders$]"],
                    }
                ]
            },
        )

    def test_build_connections_input_omits_empty_physical_tables(self):
        datasource = dict(self.prepared_datasources[0])
        datasource["tables"] = [{"name": None, "physical_table": None}]

        payload = build_connections_input(self.metadata, [datasource])

        self.assertEqual(
            payload,
            {
                "datasources": [
                    {
                        "name": "Sales Caption",
                        "connection": {"type": "excel-direct"},
                    }
                ]
            },
        )

    def test_build_all_payload_files_writes_all_payloads(self):
        with managed_tempdir() as tmpdir:
            written = build_all_payload_files(self.metadata, Path(tmpdir))

            self.assertEqual(
                sorted(written),
                [
                    "connections_input",
                    "functional_doc_input_slim",
                    "parameters_input",
                    "report_input",
                    "semantic_model_input",
                ],
            )
            sm_path = Path(tmpdir) / "semantic_model_input.json"
            semantic_model_payload = json.loads(sm_path.read_text(encoding="utf-8"))
            self.assertEqual(semantic_model_payload["datasources"][0]["name"], "Sales Caption")

    def test_build_functional_doc_input_slim_projects_balanced_fields(self):
        payload = build_functional_doc_input_slim(self.metadata)

        self.assertEqual(sorted(payload), ["actions", "dashboards", "datasources", "parameters", "worksheets"])
        self.assertEqual(
            payload["dashboards"][0],
            {"name": "Dashboard 1", "size": {"width": "100"}, "sheets": ["Sheet 1"]},
        )
        self.assertNotIn("layout_zones", payload["dashboards"][0])
        self.assertEqual(payload["worksheets"][0]["name"], "Sheet 1")
        self.assertEqual(payload["worksheets"][0]["cols_shelf"], [{"field": "Sales"}])
        self.assertNotIn("raw", json.dumps(payload))
        # Datasource now includes connection, tables, joins, relationships,
        # groups; [:TableauInternal] columns are filtered out.
        self.assertEqual(
            payload["datasources"][0],
            {
                "name": "Sales",
                "caption": "Sales Caption",
                "connection": {"type": "excel-direct"},
                "tables": [{"name": "Orders"}],
                "joins": [{"join_type": "inner"}],
                "relationships": [{"left_table": "Orders", "right_table": "Customers"}],
                "columns": [{"name": "[Sales]", "role": "measure"}],
                "calculated_fields": [{"name": "[Profit]"}],
                "groups": [{"name": "Keep", "members": ["A"]}],
            },
        )

    # ── FDD-slim metadata enrichment tests ─────────────────────────────

    def test_functional_doc_slim_filters_tableau_internal_columns(self):
        payload = build_functional_doc_input_slim(self.metadata)
        ds = payload["datasources"][0]
        col_names = [c["name"] for c in ds["columns"]]
        self.assertNotIn("[:TableauInternal]", col_names)
        self.assertIn("[Sales]", col_names)

    def test_functional_doc_slim_includes_connection_type(self):
        payload = build_functional_doc_input_slim(self.metadata)
        ds = payload["datasources"][0]
        self.assertEqual(ds["connection"], {"type": "excel-direct"})

    def test_functional_doc_slim_includes_relationships_joins_tables(self):
        payload = build_functional_doc_input_slim(self.metadata)
        ds = payload["datasources"][0]
        self.assertEqual(ds["tables"], [{"name": "Orders"}])
        self.assertEqual(ds["joins"], [{"join_type": "inner"}])
        self.assertEqual(ds["relationships"], [{"left_table": "Orders", "right_table": "Customers"}])

    def test_functional_doc_slim_includes_non_empty_groups(self):
        payload = build_functional_doc_input_slim(self.metadata)
        ds = payload["datasources"][0]
        self.assertEqual(ds["groups"], [{"name": "Keep", "members": ["A"]}])

    def test_functional_doc_slim_includes_table_calculations(self):
        metadata = {
            **self.metadata,
            "worksheets": [
                {
                    "name": "Sheet 1",
                    "cols_shelf": [],
                    "rows_shelf": [],
                    "table_calculations": [{"name": "Running Total"}],
                }
            ],
        }
        payload = build_functional_doc_input_slim(metadata)
        self.assertEqual(payload["worksheets"][0]["table_calculations"], [{"name": "Running Total"}])

    def test_functional_doc_slim_includes_reference_lines(self):
        metadata = {
            **self.metadata,
            "worksheets": [
                {
                    "name": "Sheet 1",
                    "cols_shelf": [],
                    "rows_shelf": [],
                    "reference_lines": [{"value": "average", "raw": "<ref/>"}],
                }
            ],
        }
        payload = build_functional_doc_input_slim(metadata)
        # raw keys are stripped
        self.assertEqual(payload["worksheets"][0]["reference_lines"], [{"value": "average"}])

    def test_functional_doc_slim_omits_empty_description(self):
        metadata = {
            **self.metadata,
            "datasources": [
                {
                    "name": "DS",
                    "columns": [{"name": "[Col]", "description": ""}],
                    "calculated_fields": [{"name": "[Calc]", "description": ""}],
                    "metadata_records": [{"class": "column", "local_name": "Col", "local_type": "string"}],
                }
            ],
        }
        payload = build_functional_doc_input_slim(metadata)
        ds = payload["datasources"][0]
        for col in ds.get("columns", []):
            self.assertNotIn("description", col)
        for cf in ds.get("calculated_fields", []):
            self.assertNotIn("description", cf)

    def test_functional_doc_slim_excludes_encodings(self):
        metadata = {
            **self.metadata,
            "worksheets": [
                {
                    "name": "Sheet 1",
                    "cols_shelf": [],
                    "rows_shelf": [],
                    "encodings": {"color": {"field": "[Sales]"}},
                }
            ],
        }
        payload = build_functional_doc_input_slim(metadata)
        self.assertNotIn("encodings", payload["worksheets"][0])

    def test_functional_doc_slim_omits_absent_structural_fields(self):
        """Datasource with no connection/tables/joins/relationships/groups omits those keys."""
        metadata = {
            **self.metadata,
            "datasources": [
                {
                    "name": "Bare",
                    "columns": [{"name": "[A]"}],
                    "metadata_records": [{"class": "column", "local_name": "A", "local_type": "string"}],
                }
            ],
        }
        payload = build_functional_doc_input_slim(metadata)
        ds = payload["datasources"][0]
        for key in ("connection", "tables", "joins", "relationships", "groups"):
            self.assertNotIn(key, ds, f"{key} should be absent when source data is missing")

    def test_build_all_payload_files_writes_functional_doc_input_slim_file(self):
        with managed_tempdir() as tmpdir:
            build_all_payload_files(self.metadata, Path(tmpdir))

            slim_path = Path(tmpdir) / FUNCTIONAL_DOC_INPUT_SLIM_FILENAME
            self.assertTrue(slim_path.exists())
            payload = json.loads(slim_path.read_text(encoding="utf-8"))
            self.assertIn("worksheets", payload)
