"""Assembler-level tests for semantic model PBIP output."""

import json
import re
import unittest
import uuid

from Tableau2PowerBI.agents.semantic_model.assembler import SemanticModelAssembler
from Tableau2PowerBI.agents.semantic_model.models import (
    ColumnDecision,
    ParameterDecision,
    RelationshipDecision,
    SemanticModelDecisions,
    TableDecision,
)


def _minimal_decisions(**overrides) -> SemanticModelDecisions:
    """Build a minimal valid SemanticModelDecisions for testing."""
    defaults = {
        "tables": [
            TableDecision(
                name="Sales",
                query_group="Fact",
                columns=[
                    ColumnDecision(
                        name="Order ID",
                        source_column="Order ID",
                        data_type="string",
                        summarize_by="none",
                    ),
                    ColumnDecision(
                        name="Amount",
                        source_column="Amount",
                        data_type="int64",
                        summarize_by="sum",
                    ),
                ],
                m_query=(
                    "let\n"
                    '    Source = Excel.Workbook(File.Contents("Data/Sales.xlsx"), null, true),\n'
                    '    Data = Source{[Item="Orders",Kind="Sheet"]}[Data]\n'
                    "in\n"
                    "    Data"
                ),
            ),
            TableDecision(
                name="Products",
                query_group="Dimension",
                columns=[
                    ColumnDecision(
                        name="Product ID",
                        source_column="Product ID",
                        data_type="string",
                        summarize_by="none",
                    ),
                ],
                m_query="let\n    Source = 1\nin\n    Source",
            ),
        ],
        "relationships": [
            RelationshipDecision(
                from_table="Sales",
                from_column="Order ID",
                to_table="Products",
                to_column="Product ID",
            ),
        ],
        "parameters": [
            ParameterDecision(name="Threshold", pbi_type="Number", default_value="1"),
        ],
        "source_query_culture": "it-IT",
    }
    defaults.update(overrides)
    return SemanticModelDecisions(**defaults)


class TestAssembler(unittest.TestCase):
    def _assemble(self, decisions: SemanticModelDecisions, name: str = "Book") -> dict[str, str]:
        assembler = SemanticModelAssembler(decisions, name)
        return assembler.assemble()

    def test_all_required_files_present(self):
        files = self._assemble(_minimal_decisions())
        expected = {
            "Book.SemanticModel/.platform",
            "Book.SemanticModel/definition.pbism",
            "Book.SemanticModel/.pbi/editorSettings.json",
            "Book.SemanticModel/.pbi/localSettings.json",
            "Book.SemanticModel/definition/database.tmdl",
            "Book.SemanticModel/definition/model.tmdl",
            "Book.SemanticModel/definition/expressions.tmdl",
            "Book.SemanticModel/definition/relationships.tmdl",
            "Book.SemanticModel/definition/cultures/en-US.tmdl",
            "Book.SemanticModel/diagramLayout.json",
            "Book.SemanticModel/definition/tables/Sales.tmdl",
            "Book.SemanticModel/definition/tables/Products.tmdl",
        }
        self.assertTrue(expected.issubset(files.keys()))

    def test_platform_contains_display_name(self):
        files = self._assemble(_minimal_decisions(), name="Retail Model")
        platform = json.loads(files["Retail Model.SemanticModel/.platform"])
        self.assertEqual(platform["metadata"]["displayName"], "Retail Model")

    def test_platform_has_uuid_logical_id(self):
        files = self._assemble(_minimal_decisions())
        platform = json.loads(files["Book.SemanticModel/.platform"])
        uuid.UUID(platform["config"]["logicalId"], version=4)

    def test_pbism_version(self):
        files = self._assemble(_minimal_decisions())
        pbism = json.loads(files["Book.SemanticModel/definition.pbism"])
        self.assertEqual(pbism["version"], "4.2")

    def test_database_uses_semantic_model_name(self):
        files = self._assemble(_minimal_decisions(), name="Retail Model")
        database = files["Retail Model.SemanticModel/definition/database.tmdl"]
        self.assertIn("database 'Retail Model'", database)

    def test_culture_tmdl_exact_structure(self):
        files = self._assemble(_minimal_decisions())
        culture = files["Book.SemanticModel/definition/cultures/en-US.tmdl"]
        expected = (
            "cultureInfo en-US\n"
            "\tlinguisticMetadata =\n"
            "\t\t\t{\n"
            '\t\t\t  "Version": "1.0.0",\n'
            '\t\t\t  "Language": "en-US"\n'
            "\t\t\t}\n"
            "\t\tcontentType: json\n"
        )
        self.assertEqual(culture, expected)

    def test_model_contains_ref_tables_and_culture(self):
        files = self._assemble(_minimal_decisions())
        model = files["Book.SemanticModel/definition/model.tmdl"]
        self.assertIn("ref table 'Sales'", model)
        self.assertIn("ref table 'Products'", model)
        self.assertIn("ref cultureInfo en-US", model)

    def test_model_includes_ref_expressions(self):
        files = self._assemble(_minimal_decisions())
        model = files["Book.SemanticModel/definition/model.tmdl"]
        self.assertIn("ref expression 'DataFolderPath'", model)
        self.assertIn("ref expression 'Threshold'", model)

    def test_model_no_ref_expression_without_file_sources(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="Products",
                    query_group="Dimension",
                    columns=[ColumnDecision(name="Product ID", source_column="Product ID", data_type="string")],
                    m_query="let\n    Source = 1\nin\n    Source",
                ),
            ],
            parameters=[],
            relationships=[],
        )
        files = self._assemble(decisions)
        model = files["Book.SemanticModel/definition/model.tmdl"]
        self.assertNotIn("ref expression", model)

    def test_model_includes_ref_relationships(self):
        files = self._assemble(_minimal_decisions())
        model = files["Book.SemanticModel/definition/model.tmdl"]
        self.assertRegex(model, r"ref relationship [0-9a-f\-]{36}")

    def test_model_no_ref_relationships_when_none(self):
        files = self._assemble(_minimal_decisions(relationships=[]))
        model = files["Book.SemanticModel/definition/model.tmdl"]
        self.assertNotIn("ref relationship", model)

    def test_model_pbi_query_order(self):
        files = self._assemble(_minimal_decisions())
        model = files["Book.SemanticModel/definition/model.tmdl"]
        self.assertIn("annotation PBI_QueryOrder = ['Sales','Products','DataFolderPath','Threshold']", model)

    def test_model_pbi_query_order_no_file_sources(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="Products",
                    query_group="Dimension",
                    columns=[ColumnDecision(name="Product ID", source_column="Product ID", data_type="string")],
                    m_query="let\n    Source = 1\nin\n    Source",
                ),
            ],
            parameters=[ParameterDecision(name="Threshold", pbi_type="Number", default_value="1")],
            relationships=[],
        )
        files = self._assemble(decisions)
        model = files["Book.SemanticModel/definition/model.tmdl"]
        self.assertIn("annotation PBI_QueryOrder = ['Products','Threshold']", model)

    def test_model_source_query_culture_from_decisions(self):
        files = self._assemble(_minimal_decisions(source_query_culture="fr-FR"))
        model = files["Book.SemanticModel/definition/model.tmdl"]
        self.assertIn("\tsourceQueryCulture: fr-FR", model)

    def test_expressions_from_parameters(self):
        files = self._assemble(_minimal_decisions())
        expressions = files["Book.SemanticModel/definition/expressions.tmdl"]
        self.assertIn("expression 'Threshold' = 1", expressions)
        self.assertIn('Type="Number"', expressions)

    def test_expressions_has_data_folder_path_for_file_sources(self):
        files = self._assemble(_minimal_decisions())
        expressions = files["Book.SemanticModel/definition/expressions.tmdl"]
        self.assertIn("expression 'DataFolderPath' = \"C:\\Change\\Me\"", expressions)
        self.assertIn('Type="Text"', expressions)

    def test_expressions_empty_when_no_file_sources_or_params(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="Products",
                    query_group="Dimension",
                    columns=[ColumnDecision(name="Product ID", source_column="Product ID", data_type="string")],
                    m_query="let\n    Source = 1\nin\n    Source",
                ),
            ],
            parameters=[],
            relationships=[],
        )
        files = self._assemble(decisions)
        self.assertEqual(files["Book.SemanticModel/definition/expressions.tmdl"], "")

    def test_relationships_rendered(self):
        files = self._assemble(_minimal_decisions())
        relationships = files["Book.SemanticModel/definition/relationships.tmdl"]
        self.assertIn("\tfromColumn: 'Sales'.'Order ID'", relationships)
        self.assertIn("\ttoColumn: 'Products'.'Product ID'", relationships)

    def test_inactive_relationship_rendered(self):
        decisions = _minimal_decisions(
            relationships=[
                RelationshipDecision(
                    from_table="Sales",
                    from_column="Order ID",
                    to_table="Products",
                    to_column="Product ID",
                    is_active=False,
                )
            ]
        )
        files = self._assemble(decisions)
        relationships = files["Book.SemanticModel/definition/relationships.tmdl"]
        self.assertIn("\tisActive: false", relationships)

    def test_relationships_empty_when_none(self):
        files = self._assemble(_minimal_decisions(relationships=[]))
        self.assertEqual(files["Book.SemanticModel/definition/relationships.tmdl"], "")

    def test_table_tmdl_structure(self):
        files = self._assemble(_minimal_decisions())
        table = files["Book.SemanticModel/definition/tables/Sales.tmdl"]
        self.assertIn("table 'Sales'", table)
        self.assertIn("\tpartition 'Sales' = m", table)
        self.assertIn("\t\tqueryGroup: Fact", table)

    def test_table_column_quoting(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="Customer Orders",
                    query_group="Fact",
                    columns=[
                        ColumnDecision(
                            name="Customer Name",
                            source_column="Customer Name",
                            data_type="string",
                        ),
                    ],
                    m_query="let\n    Source = 1\nin\n    Source",
                )
            ],
            relationships=[],
            parameters=[],
        )
        files = self._assemble(decisions)
        table = files["Book.SemanticModel/definition/tables/Customer Orders.tmdl"]
        self.assertIn("table 'Customer Orders'", table)
        self.assertIn("\tcolumn 'Customer Name'", table)

    def test_int64_gets_format_string(self):
        files = self._assemble(_minimal_decisions())
        table = files["Book.SemanticModel/definition/tables/Sales.tmdl"]
        self.assertIn("\t\tdataType: int64", table)
        self.assertIn("\t\tformatString: 0", table)

    def test_calc_group_table_has_standard_columns(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="Calc Group",
                    query_group="Fact",
                    columns=[],
                    is_calc_group=True,
                    calc_items=["Current", "Previous"],
                )
            ],
            relationships=[],
            parameters=[],
        )
        files = self._assemble(decisions)
        table = files["Book.SemanticModel/definition/tables/Calc Group.tmdl"]
        self.assertIn("\tcalculationGroup", table)
        self.assertIn("\t\tcalculationItem Current = SELECTEDMEASURE()", table)
        self.assertIn("\tcolumn 'Calc Group column'", table)
        self.assertIn("\tcolumn Ordinal", table)
        self.assertIn("\t\tsortByColumn: Ordinal", table)

    def test_diagram_excludes_calc_groups(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="Sales",
                    query_group="Fact",
                    columns=[ColumnDecision(name="Order ID", source_column="Order ID", data_type="string")],
                    m_query="let\n    Source = 1\nin\n    Source",
                ),
                TableDecision(
                    name="Calc Group",
                    query_group="Fact",
                    columns=[],
                    is_calc_group=True,
                    calc_items=["Default"],
                ),
            ],
            relationships=[],
            parameters=[],
        )
        files = self._assemble(decisions)
        diagram = json.loads(files["Book.SemanticModel/diagramLayout.json"])
        nodes = diagram["diagrams"][0]["nodes"]
        node_names = [node["nodeIndex"] for node in nodes]
        self.assertEqual(node_names, ["Sales"])

    def test_tab_indentation_only(self):
        files = self._assemble(_minimal_decisions())
        for path, content in files.items():
            if not path.endswith(".tmdl"):
                continue
            if path.endswith("/definition/cultures/en-US.tmdl"):
                continue
            for line in content.splitlines():
                if not line:
                    continue
                self.assertFalse(line.startswith(" "), msg=f"spaces used for indentation in {path}: {line!r}")

    def test_m_query_indented_at_four_tabs(self):
        files = self._assemble(_minimal_decisions())
        table = files["Book.SemanticModel/definition/tables/Sales.tmdl"]
        m_lines = [line for line in table.splitlines() if "File.Contents" in line or line.strip() == "let"]
        self.assertTrue(m_lines)
        for line in m_lines:
            self.assertTrue(line.startswith("\t\t\t\t"))

    def test_lineage_tags_are_valid_uuid4(self):
        files = self._assemble(_minimal_decisions())
        tags = []
        for content in files.values():
            tags.extend(re.findall(r"lineageTag: ([0-9a-f\-]{36})", content))
        self.assertTrue(tags)
        for tag in tags:
            uuid.UUID(tag, version=4)

    def test_all_lineage_tags_unique(self):
        files = self._assemble(_minimal_decisions())
        tags = []
        for content in files.values():
            tags.extend(re.findall(r"lineageTag: ([0-9a-f\-]{36})", content))
        self.assertEqual(len(tags), len(set(tags)))

    def test_data_folder_path_precedes_user_params(self):
        files = self._assemble(_minimal_decisions())
        expressions = files["Book.SemanticModel/definition/expressions.tmdl"]
        data_folder_index = expressions.index("expression 'DataFolderPath'")
        threshold_index = expressions.index("expression 'Threshold'")
        self.assertLess(data_folder_index, threshold_index)
