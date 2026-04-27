import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from Tableau2PowerBI.agents.semantic_model import (
    PBIPSemanticModelGeneratorAgent,
    _enforce_table_names,
    _resolve_pbi_table_names,
    _sanitize_table_name,
)
from Tableau2PowerBI.agents.semantic_model.models import (
    ColumnDecision,
    ParameterDecision,
    RelationshipDecision,
    SemanticModelDecisions,
    TableDecision,
    WarningDecision,
)
from Tableau2PowerBI.core.config import AgentSettings
from tests.support import managed_tempdir


def _minimal_decisions(**overrides) -> SemanticModelDecisions:
    """Build a minimal valid SemanticModelDecisions for testing."""
    defaults = {
        "tables": [
            TableDecision(
                name="TestTable",
                query_group="Fact",
                columns=[
                    ColumnDecision(
                        name="Col1",
                        source_column="Col1",
                        data_type="string",
                        summarize_by="none",
                    ),
                ],
                m_query='let\n    Source = Excel.Workbook(File.Contents("test.xlsx"), null, true)\nin\n    Source',
            ),
        ],
    }
    defaults.update(overrides)
    return SemanticModelDecisions(**defaults)


def _minimal_response(**overrides) -> str:
    """Return JSON string of a minimal decisions payload."""
    d = _minimal_decisions(**overrides)
    return d.model_dump_json()


class TestModels(unittest.TestCase):
    """Pydantic model validation."""

    def test_valid_decisions_accepted(self):
        d = _minimal_decisions()
        self.assertEqual(len(d.tables), 1)
        self.assertEqual(d.tables[0].name, "TestTable")
        self.assertEqual(d.source_query_culture, "en-US")

    def test_invalid_data_type_rejected(self):
        with self.assertRaises(ValidationError):
            SemanticModelDecisions(
                tables=[
                    TableDecision(
                        name="T",
                        query_group="Fact",
                        columns=[
                            ColumnDecision(
                                name="C",
                                source_column="C",
                                data_type="varchar",  # invalid
                                summarize_by="none",
                            )
                        ],
                        m_query="let\n    Source = 1\nin\n    Source",
                    )
                ]
            )

    def test_invalid_query_group_rejected(self):
        with self.assertRaises(ValidationError):
            TableDecision(
                name="T",
                query_group="Other",  # invalid
                columns=[],
                m_query="",
            )

    def test_invalid_pbi_type_rejected(self):
        with self.assertRaises(ValidationError):
            ParameterDecision(
                name="P",
                pbi_type="Currency",  # invalid — not a known alias
                default_value="1",
            )

    def test_pbi_type_alias_normalised(self):
        """Common LLM variants like 'Decimal' are normalised."""
        p = ParameterDecision(
            name="P",
            pbi_type="Decimal",
            default_value="1",
        )
        self.assertEqual(p.pbi_type, "Number")

    def test_defaults_applied(self):
        d = SemanticModelDecisions(tables=[])
        self.assertEqual(d.relationships, [])
        self.assertEqual(d.parameters, [])
        self.assertEqual(d.warnings, [])
        self.assertEqual(d.source_query_culture, "en-US")


class TestAgentParsing(unittest.TestCase):
    """Agent-level parsing and file writing."""

    def _build_agent(self, tmpdir: Path) -> PBIPSemanticModelGeneratorAgent:
        agent = object.__new__(PBIPSemanticModelGeneratorAgent)
        agent.skill_name = "pbip_semantic_model_generator_agent"
        agent.settings = AgentSettings(
            project_endpoint="https://example.test",
            output_root=tmpdir,
        )
        agent.logger = __import__("logging").getLogger("test.pbip")
        return agent

    def test_parse_decisions_from_clean_json(self):
        response = _minimal_response()
        decisions = PBIPSemanticModelGeneratorAgent._parse_decisions(response)
        self.assertEqual(len(decisions.tables), 1)

    def test_parse_decisions_strips_fences(self):
        response = f"```json\n{_minimal_response()}\n```"
        decisions = PBIPSemanticModelGeneratorAgent._parse_decisions(response)
        self.assertEqual(len(decisions.tables), 1)

    def test_parse_decisions_rejects_invalid_json(self):
        with self.assertRaises(ValueError):
            PBIPSemanticModelGeneratorAgent._parse_decisions("not json")

    def test_parse_decisions_rejects_invalid_schema(self):
        with self.assertRaises((ValueError, ValidationError)):
            PBIPSemanticModelGeneratorAgent._parse_decisions('{"tables": "not a list"}')

    def test_save_creates_files_on_disk(self):
        with managed_tempdir() as tmpdir:
            agent = self._build_agent(tmpdir)
            agent.save_pbip_semantic_model(_minimal_response(), "Workbook")

            model_file = (
                tmpdir
                / "pbip_semantic_model_generator_agent"
                / "Workbook"
                / "Workbook.SemanticModel"
                / "definition"
                / "model.tmdl"
            )
            self.assertTrue(model_file.exists())

    def test_save_uses_explicit_semantic_model_name(self):
        with managed_tempdir() as tmpdir:
            agent = self._build_agent(tmpdir)
            agent.save_pbip_semantic_model(_minimal_response(), "Workbook", semantic_model_name="Custom")

            self.assertTrue(
                (
                    tmpdir
                    / "pbip_semantic_model_generator_agent"
                    / "Workbook"
                    / "Custom.SemanticModel"
                    / "definition"
                    / "model.tmdl"
                ).exists()
            )

    def test_tmdl_files_have_crlf_line_endings(self):
        with managed_tempdir() as tmpdir:
            agent = self._build_agent(tmpdir)
            agent.save_pbip_semantic_model(_minimal_response(), "Workbook")

            model_file = (
                tmpdir
                / "pbip_semantic_model_generator_agent"
                / "Workbook"
                / "Workbook.SemanticModel"
                / "definition"
                / "model.tmdl"
            )
            raw = model_file.read_bytes()
            self.assertIn(b"\r\n", raw, "TMDL must use CRLF")
            # No bare LF (every \n must be preceded by \r)
            normalized = raw.replace(b"\r\n", b"")
            self.assertNotIn(b"\n", normalized, "Found bare LF after stripping CRLF")

    def test_json_files_not_crlf(self):
        with managed_tempdir() as tmpdir:
            agent = self._build_agent(tmpdir)
            agent.save_pbip_semantic_model(_minimal_response(), "Workbook")

            pbism = (
                tmpdir
                / "pbip_semantic_model_generator_agent"
                / "Workbook"
                / "Workbook.SemanticModel"
                / "definition.pbism"
            )
            raw = pbism.read_bytes()
            # JSON is a single line - should not have \r\n forced
            self.assertNotIn(b"\r\n", raw)

    def test_warnings_file_written(self):
        d = _minimal_decisions(
            warnings=[
                WarningDecision(
                    code="WARN_TEST",
                    message="Test warning",
                ),
            ]
        )
        with managed_tempdir() as tmpdir:
            agent = self._build_agent(tmpdir)
            agent.save_pbip_semantic_model(d.model_dump_json(), "Workbook")

            warnings_file = tmpdir / "pbip_semantic_model_generator_agent" / "Workbook" / "migration_warnings.json"
            self.assertTrue(warnings_file.exists())
            data = json.loads(warnings_file.read_text(encoding="utf-8"))
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["code"], "WARN_TEST")

    def test_warnings_file_empty_array_when_no_warnings(self):
        with managed_tempdir() as tmpdir:
            agent = self._build_agent(tmpdir)
            agent.save_pbip_semantic_model(_minimal_response(), "Workbook")

            warnings_file = tmpdir / "pbip_semantic_model_generator_agent" / "Workbook" / "migration_warnings.json"
            self.assertTrue(warnings_file.exists())
            self.assertEqual(json.loads(warnings_file.read_text(encoding="utf-8")), [])


class TestSanitizeTableName(unittest.TestCase):
    """Tests for _sanitize_table_name."""

    def test_simple_name(self):
        self.assertEqual(_sanitize_table_name("Ordini"), "Ordini")

    def test_strips_whitespace(self):
        self.assertEqual(_sanitize_table_name("  Ordini  "), "Ordini")

    def test_replaces_illegal_chars(self):
        self.assertEqual(
            _sanitize_table_name('Esempio - Supermercato/foo:bar*baz?"qux'), "Esempio - Supermercato_foo_bar_baz__qux"
        )

    def test_backslash_replaced(self):
        self.assertEqual(_sanitize_table_name("path\\to\\file"), "path_to_file")


class TestResolvePbiTableNames(unittest.TestCase):
    """Tests for _resolve_pbi_table_names — deterministic table naming."""

    def _metadata(self, datasources: list[dict]) -> dict:
        return {"datasources": datasources}

    def test_single_table_uses_datasource_name(self):
        meta = self._metadata(
            [
                {
                    "name": "Obiettivo di vendita",
                    "tables": [{"name": "Sheet1", "columns": [{"name": "Col1"}]}],
                },
            ]
        )
        result = _resolve_pbi_table_names(meta)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pbi_table_name"], "Obiettivo di vendita")

    def test_multi_table_uses_sheet_names(self):
        meta = self._metadata(
            [
                {
                    "name": "Esempio - Supermercato",
                    "tables": [
                        {"name": "Ordini", "columns": [{"name": "C1"}]},
                        {"name": "Persone", "columns": [{"name": "C2"}]},
                        {"name": "Resi", "columns": [{"name": "C3"}]},
                    ],
                },
            ]
        )
        result = _resolve_pbi_table_names(meta)
        names = [e["pbi_table_name"] for e in result]
        self.assertEqual(names, ["Ordini", "Persone", "Resi"])

    def test_duplicate_names_get_suffixes(self):
        meta = self._metadata(
            [
                {"name": "DS_A", "tables": [{"name": "Sheet1", "columns": []}]},
                {"name": "DS_B", "tables": [{"name": "Sheet1", "columns": []}]},
            ]
        )
        # Both are single-table → use DS name. No collision since DS names differ.
        result = _resolve_pbi_table_names(meta)
        self.assertEqual(result[0]["pbi_table_name"], "DS_A")
        self.assertEqual(result[1]["pbi_table_name"], "DS_B")

    def test_duplicate_sanitized_names_deduped(self):
        meta = self._metadata(
            [
                {"name": "Same", "tables": [{"name": "X", "columns": []}]},
                {"name": "Same", "tables": [{"name": "Y", "columns": []}]},
            ]
        )
        result = _resolve_pbi_table_names(meta)
        self.assertEqual(result[0]["pbi_table_name"], "Same")
        self.assertEqual(result[1]["pbi_table_name"], "Same_2")

    def test_illegal_chars_sanitized(self):
        meta = self._metadata(
            [
                {"name": 'File/Path:Name*Bad?"', "tables": [{"name": "Only", "columns": []}]},
            ]
        )
        result = _resolve_pbi_table_names(meta)
        self.assertNotIn("/", result[0]["pbi_table_name"])
        self.assertNotIn(":", result[0]["pbi_table_name"])
        self.assertNotIn("*", result[0]["pbi_table_name"])

    def test_supermercato_like_workbook(self):
        """Full scenario mirroring the Supermercato workbook structure."""
        meta = self._metadata(
            [
                {
                    "name": "Obiettivo di vendita",
                    "tables": [{"name": "Sheet1", "columns": [{"name": "Categoria"}, {"name": "Segmento"}]}],
                },
                {
                    "name": "Commissione vendite",
                    "tables": [{"name": "Sales Commission.csv", "columns": [{"name": "Regione"}, {"name": "Vendite"}]}],
                },
                {
                    "name": "Esempio - Supermercato",
                    "tables": [
                        {"name": "Ordini", "columns": [{"name": "ID riga"}, {"name": "Vendite"}]},
                        {"name": "Persone", "columns": [{"name": "Regione"}, {"name": "Manager regionale"}]},
                        {"name": "Resi", "columns": [{"name": "ID ordine"}, {"name": "Reso"}]},
                    ],
                },
            ]
        )
        result = _resolve_pbi_table_names(meta)
        names = [e["pbi_table_name"] for e in result]
        self.assertEqual(
            names,
            [
                "Obiettivo di vendita",
                "Commissione vendite",
                "Ordini",
                "Persone",
                "Resi",
            ],
        )

    def test_empty_datasources(self):
        result = _resolve_pbi_table_names({"datasources": []})
        self.assertEqual(result, [])

    def test_no_datasources_key(self):
        result = _resolve_pbi_table_names({})
        self.assertEqual(result, [])


class TestEnforceTableNames(unittest.TestCase):
    """Tests for _enforce_table_names — post-LLM name correction."""

    def test_matching_names_unchanged(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="Ordini",
                    query_group="Fact",
                    columns=[ColumnDecision(name="C", source_column="ID riga", data_type="string")],
                    m_query="let\n    Source = 1\nin\n    Source",
                ),
            ]
        )
        entries = [{"pbi_table_name": "Ordini", "source_columns": {"ID riga"}}]
        _enforce_table_names(decisions, entries)
        self.assertEqual(decisions.tables[0].name, "Ordini")

    def test_wrong_name_corrected_by_column_overlap(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="WrongName",
                    query_group="Fact",
                    columns=[ColumnDecision(name="C", source_column="ID riga", data_type="string")],
                    m_query="let\n    Source = 1\nin\n    Source",
                ),
            ]
        )
        entries = [{"pbi_table_name": "Ordini", "source_columns": {"ID riga", "Vendite"}}]
        _enforce_table_names(decisions, entries)
        self.assertEqual(decisions.tables[0].name, "Ordini")

    def test_relationships_updated_on_rename(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="FactBad",
                    query_group="Fact",
                    columns=[ColumnDecision(name="FK", source_column="RegionID", data_type="string")],
                    m_query="let\n    Source = 1\nin\n    Source",
                ),
                TableDecision(
                    name="DimBad",
                    query_group="Dimension",
                    columns=[ColumnDecision(name="PK", source_column="Region", data_type="string")],
                    m_query="let\n    Source = 1\nin\n    Source",
                ),
            ],
            relationships=[
                RelationshipDecision(
                    from_table="FactBad", from_column="RegionID", to_table="DimBad", to_column="Region"
                ),
            ],
        )
        entries = [
            {"pbi_table_name": "FactGood", "source_columns": {"RegionID", "Amount"}},
            {"pbi_table_name": "DimGood", "source_columns": {"Region", "Manager"}},
        ]
        _enforce_table_names(decisions, entries)
        self.assertEqual(decisions.tables[0].name, "FactGood")
        self.assertEqual(decisions.tables[1].name, "DimGood")
        self.assertEqual(decisions.relationships[0].from_table, "FactGood")
        self.assertEqual(decisions.relationships[0].to_table, "DimGood")

    def test_mixed_correct_and_wrong_names(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="Ordini",
                    query_group="Fact",
                    columns=[ColumnDecision(name="C", source_column="ID riga", data_type="string")],
                    m_query="let\n    Source = 1\nin\n    Source",
                ),
                TableDecision(
                    name="WrongPersName",
                    query_group="Dimension",
                    columns=[ColumnDecision(name="C", source_column="Manager", data_type="string")],
                    m_query="let\n    Source = 1\nin\n    Source",
                ),
            ]
        )
        entries = [
            {"pbi_table_name": "Ordini", "source_columns": {"ID riga", "Vendite"}},
            {"pbi_table_name": "Persone", "source_columns": {"Manager", "Regione"}},
        ]
        _enforce_table_names(decisions, entries)
        self.assertEqual(decisions.tables[0].name, "Ordini")
        self.assertEqual(decisions.tables[1].name, "Persone")


class TestBuildPromptTableNames(unittest.TestCase):
    """Tests for _build_prompt with TDD-based table name injection."""

    def test_table_names_injected_in_prompt(self):
        tdd_sm = {
            "tables": [
                {"name": "DS1", "source_datasource": "DS1", "source_table": "Sheet1", "columns": []},
                {"name": "Ordini", "source_datasource": "DS2", "source_table": "Ordini", "columns": []},
            ]
        }
        entries = [
            {
                "datasource_name": "DS1",
                "table_index": 0,
                "original_table_name": "Sheet1",
                "pbi_table_name": "DS1",
                "source_columns": set(),
            },
            {
                "datasource_name": "DS2",
                "table_index": 1,
                "original_table_name": "Ordini",
                "pbi_table_name": "Ordini",
                "source_columns": set(),
            },
        ]
        prompt = PBIPSemanticModelGeneratorAgent._build_prompt(tdd_sm, {}, "TestModel", entries)
        self.assertIn("Pre-computed Table Names", prompt)
        self.assertIn('"DS1"', prompt)
        self.assertIn('"Ordini"', prompt)
        self.assertIn("MUST be used EXACTLY", prompt)

    def test_prompt_without_entries_has_no_mapping(self):
        prompt = PBIPSemanticModelGeneratorAgent._build_prompt({}, {}, "TestModel")
        self.assertNotIn("Pre-computed Table Names", prompt)

    def test_prompt_includes_tdd_semantic_model(self):
        tdd_sm = {"tables": [{"name": "Sales", "columns": []}]}
        prompt = PBIPSemanticModelGeneratorAgent._build_prompt(tdd_sm, {}, "TestModel")
        self.assertIn("Target Technical Design", prompt)
        self.assertIn('"Sales"', prompt)

    def test_prompt_includes_dax_summary(self):
        tdd_dax = {
            "measures": [
                {"owner_table": "Sales", "caption": "Total Revenue", "tableau_name": "Revenue"},
            ]
        }
        prompt = PBIPSemanticModelGeneratorAgent._build_prompt({}, tdd_dax, "TestModel")
        self.assertIn("DAX Measures Summary", prompt)
        self.assertIn("Total Revenue", prompt)
