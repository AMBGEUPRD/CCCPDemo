from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from Tableau2PowerBI.agents.powerbi_metadata_extractor import PowerBIMetadataExtractorAgent
from Tableau2PowerBI.agents.powerbi_metadata_extractor.pbip_parsing import extract_pbip_metadata
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.source_detection import extract_metadata_with_dispatch
from tests.support import managed_tempdir

_OI_PBIP_ZIP = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "input"
    / "OI Business Dashboard"
    / "OI Business Dashboard.zip"
)


def _write_pbip_zip(
    path: Path,
    *,
    project_name: str = "SalesModel",
    include_semantic_model: bool = True,
) -> None:
    with ZipFile(path, "w") as zf:
        zf.writestr(
            f"{project_name}.pbip",
            f"""{{
  "version": "1.0",
  "artifacts": [{{"report": {{"path": "{project_name}.Report"}}}}],
  "settings": {{"enableAutoRecovery": true}}
}}""",
        )
        zf.writestr(
            f"{project_name}.Report/definition.pbir",
            f"""{{
  "version": "4.0",
  "datasetReference": {{"byPath": {{"path": "../{project_name}.SemanticModel"}}}}
}}""",
        )
        zf.writestr(
            f"{project_name}.Report/definition/report.json",
            """{
  "themeCollection": {"baseTheme": {"name": "Corporate", "type": "SharedResources"}},
  "settings": {"allowChangeFilterTypes": true}
}""",
        )
        zf.writestr(
            f"{project_name}.Report/definition/pages/pages.json",
            """{
  "pageOrder": ["PageOne"],
  "activePageName": "PageOne"
}""",
        )
        zf.writestr(
            f"{project_name}.Report/definition/pages/PageOne/page.json",
            """{
  "name": "PageOne",
  "displayName": "Overview",
  "displayOption": "FitToPage",
  "width": 1280,
  "height": 720
}""",
        )
        zf.writestr(
            f"{project_name}.Report/definition/pages/PageOne/visuals/VisualOne/visual.json",
            """{
  "name": "VisualOne",
  "position": {"x": 0, "y": 0, "width": 400, "height": 200},
  "visual": {
    "visualType": "barChart",
    "query": {
      "queryState": {
        "Category": {
          "projections": [{
            "field": {
              "Column": {
                "Expression": {"SourceRef": {"Entity": "Table"}},
                "Property": "category"
              }
            }
          }]
        },
        "Tooltips": {
          "projections": [{
            "field": {
              "Column": {
                "Property": "category"
              }
            }
          }]
        },
        "Y": {
          "projections": [{
            "field": {
              "Aggregation": {
                "Expression": {
                  "Column": {
                    "Expression": {"SourceRef": {"Entity": "Table"}},
                    "Property": "amount"
                  }
                },
                "Function": 0
              }
            }
          }]
        }
      }
    }
  },
  "filterConfig": {
    "filters": [{
      "name": "FilterOne",
      "field": {
        "Column": {
          "Expression": {"SourceRef": {"Entity": "Table"}},
          "Property": "category"
        }
      },
      "type": "Categorical"
    }]
  }
}""",
        )
        zf.writestr(
            f"{project_name}.Report/definition/pages/PageOne/visuals/GroupOne/visual.json",
            """{
  "name": "GroupOne",
  "position": {"x": 20, "y": 250, "width": 500, "height": 120},
  "visualGroup": {
    "displayName": "Layout Group",
    "groupMode": "ScaleMode"
  }
}""",
        )
        zf.writestr(f"{project_name}.Report/.pbi/localSettings.json", "{}")

        if include_semantic_model:
            zf.writestr(f"{project_name}.SemanticModel/definition.pbism", '{"version": "1.0"}')
            zf.writestr(
                f"{project_name}.SemanticModel/definition/model.tmdl",
                """model Model
\tculture: en-US
\tdefaultPowerBIDataSourceVersion: powerBI_V3
annotation PBI_QueryOrder = ["Table"]
ref table Table
ref relationship rel_1
ref cultureInfo en-US
""",
            )
            zf.writestr(
                f"{project_name}.SemanticModel/definition/tables/Table.tmdl",
                """table Table
\tcolumn category
\t\tdataType: string
\t\tsummarizeBy: none
\t\tsourceColumn: category

\tcolumn amount
\t\tdataType: int64
\t\tsummarizeBy: sum
\t\tsourceColumn: amount

\tcolumn amount_bucket = INT([amount] / 10)
\t\tdataType: int64
\t\tsummarizeBy: none

\tcolumn amount_label =
\t\t\tIF([amount] > 10,
\t\t\t\t"large",
\t\t\t\t"small")
\t\tdataType: string
\t\tsummarizeBy: none

\tpartition Table = m
\t\tmode: import
\t\tsource =
\t\t\tlet
\t\t\t\tSource = #table({"category", "amount"}, {})
\t\t\tin
\t\t\t\tSource

\tannotation PBI_ResultType = Table
""",
            )
            zf.writestr(
                f"{project_name}.SemanticModel/definition/measures.tmdl",
                """table Table

\tmeasure Total Amount =
\t\t\tVAR base = SUM('Table'[amount])
\t\t\tRETURN base
\t\tformatString: #,##0

\tmeasure Average Amount = AVERAGE('Table'[amount])
\t\tformatString: #,##0.00
""",
            )
            zf.writestr(
                f"{project_name}.SemanticModel/definition/relationships.tmdl",
                """relationship rel_1
\tfromColumn: 'Table'.'category'
\ttoColumn: 'Table'.'category'
""",
            )
            zf.writestr(
                f"{project_name}.SemanticModel/definition/expressions.tmdl",
                """expression Param = 1 meta [IsParameterQuery=true, Type="Number", IsParameterQueryRequired=true]
\tqueryGroup: Parameters
\tannotation PBI_ResultType = Number
""",
            )
            zf.writestr(
                f"{project_name}.SemanticModel/definition/cultures/en-US.tmdl",
                """cultureInfo en-US
\tcontentType: json
""",
            )
            zf.writestr(f"{project_name}.SemanticModel/.pbi/editorSettings.json", "{}")


class TestPowerBIMetadataExtractor:
    def test_extract_powerbi_metadata_writes_expected_outputs(self) -> None:
        with managed_tempdir() as tmpdir:
            zip_path = tmpdir / "upload.zip"
            _write_pbip_zip(zip_path)
            settings = AgentSettings(project_endpoint="https://example.test", output_root=tmpdir / "output")
            agent = PowerBIMetadataExtractorAgent(settings=settings)

            result = json.loads(agent.extract_powerbi_metadata(str(zip_path)))

            output_dir = tmpdir / "output" / "powerbi_metadata_extractor_agent" / "SalesModel"
            assert (output_dir / "powerbi_metadata.json").exists()
            assert result["source_format"] == "pbip"
            assert result["pbip"]["project"]["name"] == "SalesModel"
            assert result["pbip"]["report"]["pages"][0]["display_name"] == "Overview"
            assert result["pbip"]["semantic_model"]["tables"][0]["columns"][0]["name"] == "category"
            assert result["pbip"]["semantic_model"]["tables"][0]["measures"][0]["name"] == "Total Amount"
            assert any(
                visual["container_kind"] == "group" and visual["group_mode"] == "ScaleMode"
                for visual in result["pbip"]["report"]["pages"][0]["visuals"]
            )

    def test_extract_powerbi_metadata_captures_multiline_dax_and_calculated_columns(self) -> None:
        with managed_tempdir() as tmpdir:
            zip_path = tmpdir / "upload.zip"
            _write_pbip_zip(zip_path)

            result = extract_pbip_metadata(zip_path)
            table = result["pbip"]["semantic_model"]["tables"][0]
            measures = {measure["name"]: measure for measure in table["measures"]}
            columns = {column["name"]: column for column in table["columns"]}

            assert "VAR base = SUM('Table'[amount])" in measures["Total Amount"]["expression"]
            assert measures["Total Amount"]["format_string"] == "#,##0"
            assert measures["Average Amount"]["format_string"] == "#,##0.00"

            assert columns["amount_bucket"]["is_calculated"] is True
            assert columns["amount_bucket"]["expression"] == "INT([amount] / 10)"
            assert columns["amount_label"]["is_calculated"] is True
            assert "IF([amount] > 10," in columns["amount_label"]["expression"]
            assert columns["category"]["is_calculated"] is False
            assert columns["category"]["source_column"] == "category"

    def test_extract_powerbi_metadata_captures_expression_metadata_and_dedupes_bindings(self) -> None:
        with managed_tempdir() as tmpdir:
            zip_path = tmpdir / "upload.zip"
            _write_pbip_zip(zip_path)

            result = extract_pbip_metadata(zip_path)
            expression = result["pbip"]["semantic_model"]["expressions"][0]
            bar_chart = next(
                visual for visual in result["pbip"]["report"]["pages"][0]["visuals"] if visual["visual_type"] == "barChart"
            )
            field_bindings = bar_chart["field_bindings"]

            assert expression["kind"] == "parameter_query"
            assert expression["result_type"] == "Number"
            assert expression["meta"]["is_parameter_query"] is True
            assert expression["query_group"] == "Parameters"
            assert expression["expression"] == "1"

            category_refs = [binding for binding in field_bindings if binding["property"] == "category"]
            assert category_refs == [{"kind": "column", "entity": "Table", "property": "category"}]

    def test_extract_powerbi_metadata_warns_when_semantic_model_missing(self) -> None:
        with managed_tempdir() as tmpdir:
            zip_path = tmpdir / "upload.zip"
            _write_pbip_zip(zip_path, include_semantic_model=False)
            settings = AgentSettings(project_endpoint="https://example.test", output_root=tmpdir / "output")
            agent = PowerBIMetadataExtractorAgent(settings=settings)

            result = json.loads(agent.extract_powerbi_metadata(str(zip_path)))

            warnings = result["pbip"]["warnings"]
            assert any(w["code"] == "missing_semantic_model" for w in warnings)
            assert any(
                visual["visual_type"] == "barChart"
                for visual in result["pbip"]["report"]["pages"][0]["visuals"]
            )

    def test_extract_metadata_with_dispatch_routes_pbip(self) -> None:
        with managed_tempdir() as tmpdir:
            zip_path = tmpdir / "upload.zip"
            _write_pbip_zip(zip_path)
            settings = AgentSettings(project_endpoint="https://example.test", output_root=tmpdir / "output")

            result = extract_metadata_with_dispatch(zip_path, settings=settings)

            assert result.source_format == "pbip"
            assert result.workbook_name == "SalesModel"
            assert result.metadata_agent_name == "powerbi_metadata_extractor_agent"

    def test_real_oi_dashboard_regression_extracts_dax_and_calculated_columns(self) -> None:
        result = extract_pbip_metadata(_OI_PBIP_ZIP)

        measure_table = next(table for table in result["pbip"]["semantic_model"]["tables"] if table["name"] == "Measure")
        measures = {measure["name"]: measure for measure in measure_table["measures"]}
        expressions = result["pbip"]["semantic_model"]["expressions"]
        calculated_columns = [
            column
            for table in result["pbip"]["semantic_model"]["tables"]
            for column in table.get("columns", [])
            if column.get("is_calculated")
        ]
        page_visuals = [
            visual
            for page in result["pbip"]["report"]["pages"]
            for visual in page.get("visuals", [])
        ]

        assert "VAR m = CALCULATE" in measures["LastAssessedSites"]["expression"]
        assert "CALCULATE([LastAssessedControlPoint]" in measures["LastGapFound"]["expression"]
        assert measures["TotalSite"]["format_string"] == 0
        assert any(column["name"] == "Year" and column["expression"] == "YEAR([Date])" for column in calculated_columns)
        assert all("=" not in column["name"] for column in calculated_columns)
        assert expressions[0]["kind"] == "parameter_query"
        assert expressions[0]["result_type"] == "Text"
        assert expressions[0]["expression"] == '"https://oi-run.nestle.com/r/0D42F08D-F947-48FC-91E4-2AC74DA224D2"'
        assert any(visual["container_kind"] == "group" for visual in page_visuals)
