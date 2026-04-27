"""Tests for the Target Technical Documentation (TDD) Agent.

Covers: Pydantic model validation, renderer output, and edge cases — all
without LLM calls.
"""

import asyncio
import logging
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from Tableau2PowerBI.agents.target_technical_doc.models import (
    AssessmentWarning,
    ColumnDesign,
    DataModelDesign,
    DaxMeasuresDesign,
    EntityResolutionMap,
    FieldBinding,
    MeasureDesign,
    MigrationAssessment,
    PageDesign,
    ParameterDesign,
    RelationshipDesign,
    ReportDesign,
    SemanticModelDesign,
    TableDesign,
    TargetTechnicalDocumentation,
    UntranslatableItem,
    VisualDesign,
)
from Tableau2PowerBI.core.agent.base import ContextLengthExceededError

# ── Helpers ───────────────────────────────────────────────────────────


def _valid_column(**overrides) -> dict:
    """Build a valid ColumnDesign dict."""
    base = {
        "name": "Vendite",
        "source_column": "Vendite",
        "data_type": "double",
        "summarize_by": "sum",
        "description": "Total sales amount",
    }
    base.update(overrides)
    return base


def _valid_m_query_strategy(**overrides) -> dict:
    """Build a valid MQueryStrategy dict."""
    base = {
        "connector_type": "Excel.Workbook",
        "source_expression": 'DataFolderPath & "\\Data\\file.xlsx"',
        "navigation_steps": ['Source{[Name="Ordini"]}[Data]'],
        "notes": "",
    }
    base.update(overrides)
    return base


def _valid_table(**overrides) -> dict:
    """Build a valid TableDesign dict."""
    base = {
        "name": "Ordini",
        "source_datasource": "Esempio - Supermercato",
        "source_table": "Ordini",
        "query_group": "Fact",
        "columns": [_valid_column()],
        "m_query_strategy": _valid_m_query_strategy(),
        "description": "Main transaction table",
    }
    base.update(overrides)
    return base


def _valid_relationship(**overrides) -> dict:
    """Build a valid RelationshipDesign dict."""
    base = {
        "from_table": "Ordini",
        "from_column": "ID cliente",
        "to_table": "Persone",
        "to_column": "ID cliente",
        "cardinality": "many-to-one",
        "cross_filter_direction": "single",
        "confidence": "high",
    }
    base.update(overrides)
    return base


def _valid_parameter(**overrides) -> dict:
    """Build a valid ParameterDesign dict."""
    base = {
        "name": "Nuova quota",
        "tableau_name": "[Nuova quota]",
        "pbi_type": "Number",
        "default_value": "100000",
        "description": "Sales target quota",
    }
    base.update(overrides)
    return base


def _valid_semantic_model(**overrides) -> dict:
    """Build a valid SemanticModelDesign dict."""
    base = {
        "tables": [_valid_table()],
        "relationships": [_valid_relationship()],
        "parameters": [_valid_parameter()],
        "source_query_culture": "it-IT",
    }
    base.update(overrides)
    return base


def _valid_measure(**overrides) -> dict:
    """Build a valid MeasureDesign dict."""
    base = {
        "tableau_name": "[Calculation_9921103144103743]",
        "caption": "Rapporto profitto",
        "owner_table": "Ordini",
        "formula": "SUM([Profitto])/SUM([Vendite])",
        "data_type": "real",
        "translatability": "direct",
        "target_dax_approach": "DIVIDE(SUM('Ordini'[Profitto]), SUM('Ordini'[Vendite]))",
        "dependencies": [],
        "notes": "",
    }
    base.update(overrides)
    return base


def _valid_dax_measures(**overrides) -> dict:
    """Build a valid DaxMeasuresDesign dict."""
    base = {
        "measures": [_valid_measure()],
        "untranslatable": [],
    }
    base.update(overrides)
    return base


def _valid_field_binding(**overrides) -> dict:
    """Build a valid FieldBinding dict."""
    base = {
        "tableau_field": "[Vendite]",
        "pbi_table": "Ordini",
        "pbi_field": "Vendite",
        "field_kind": "Aggregation",
        "aggregation": "sum",
    }
    base.update(overrides)
    return base


def _valid_visual(**overrides) -> dict:
    """Build a valid VisualDesign dict."""
    base = {
        "worksheet_name": "Dispersione cliente",
        "visual_type": "scatterChart",
        "title": "Customer Scatter",
        "position": {"x": 5, "y": 95, "width": 600, "height": 400},
        "field_bindings": [_valid_field_binding()],
        "filters": ["Filter by region"],
    }
    base.update(overrides)
    return base


def _valid_page(**overrides) -> dict:
    """Build a valid PageDesign dict."""
    base = {
        "dashboard_name": "Clienti",
        "display_name": "Clienti",
        "width": 1280,
        "height": 720,
        "visuals": [_valid_visual()],
    }
    base.update(overrides)
    return base


def _valid_report(**overrides) -> dict:
    """Build a valid ReportDesign dict."""
    base = {
        "pages": [_valid_page()],
        "standalone_worksheets": ["Rapporto profitto per citta"],
        "entity_resolution": {
            "datasource_to_table": {
                "federated.0hgpf0j1fdpvv316shikk0mmdlec": "Ordini",
            },
            "calculated_field_map": {
                "Calculation_9921103144103743": "Rapporto profitto",
            },
        },
    }
    base.update(overrides)
    return base


def _valid_assessment(**overrides) -> dict:
    """Build a valid MigrationAssessment dict."""
    base = {
        "complexity_score": "medium",
        "summary": "Workbook has 3 data sources and 6 dashboards.",
        "warnings": [
            {
                "code": "WARN_TABLE_CALC",
                "severity": "warning",
                "message": "Table calc cannot be translated",
                "source_element": "Calc_123",
                "recommendation": "Manual redesign needed",
            }
        ],
        "manual_items": ["Review Running Total Sales measure"],
    }
    base.update(overrides)
    return base


def _valid_tdd(**overrides) -> dict:
    """Build a valid TargetTechnicalDocumentation dict."""
    base = {
        "semantic_model": _valid_semantic_model(),
        "dax_measures": _valid_dax_measures(),
        "report": _valid_report(),
        "assessment": _valid_assessment(),
    }
    base.update(overrides)
    return base


def _valid_data_model_design(**overrides) -> dict:
    """Build a valid DataModelDesign dict (Call 1 output)."""
    base = {
        "semantic_model": _valid_semantic_model(),
        "dax_measures": _valid_dax_measures(),
        "assessment": _valid_assessment(),
    }
    base.update(overrides)
    return base


# ════════════════════════════════════════════════════════════════════════
#  Model Validation Tests
# ════════════════════════════════════════════════════════════════════════


class SemanticModelDesignTests(unittest.TestCase):
    """Tests for SemanticModelDesign validation."""

    def test_valid_full_model(self):
        """A complete semantic model design parses correctly."""
        sm = SemanticModelDesign.model_validate(_valid_semantic_model())
        self.assertEqual(len(sm.tables), 1)
        self.assertEqual(sm.tables[0].name, "Ordini")
        self.assertEqual(sm.source_query_culture, "it-IT")

    def test_empty_tables_fails(self):
        """An empty tables list raises a validation error."""
        with self.assertRaises(ValidationError):
            SemanticModelDesign.model_validate(
                _valid_semantic_model(tables=[]),
            )

    def test_invalid_query_group_fails(self):
        """An invalid query_group value raises a validation error."""
        with self.assertRaises(ValidationError):
            TableDesign.model_validate(
                _valid_table(query_group="InvalidGroup"),
            )

    def test_column_type_literal(self):
        """Column data_type must be one of the allowed literals."""
        col = ColumnDesign.model_validate(
            _valid_column(data_type="int64"),
        )
        self.assertEqual(col.data_type, "int64")

        with self.assertRaises(ValidationError):
            ColumnDesign.model_validate(
                _valid_column(data_type="float"),
            )

    def test_relationship_cardinality(self):
        """Relationship cardinality must be a valid literal."""
        rel = RelationshipDesign.model_validate(
            _valid_relationship(cardinality="one-to-one"),
        )
        self.assertEqual(rel.cardinality, "one-to-one")

    def test_parameter_pbi_type(self):
        """Parameter pbi_type must be in the allowed set."""
        with self.assertRaises(ValidationError):
            ParameterDesign.model_validate(
                _valid_parameter(pbi_type="Currency"),
            )

    def test_parameter_pbi_type_alias_normalised(self):
        """Common LLM variants like 'Decimal' are normalised to 'Number'."""
        p = ParameterDesign.model_validate(
            _valid_parameter(pbi_type="Decimal"),
        )
        self.assertEqual(p.pbi_type, "Number")

    def test_minimal_table(self):
        """A table with only required fields validates."""
        data = {
            "name": "T",
            "source_datasource": "DS",
            "source_table": "ST",
            "query_group": "Fact",
            "columns": [],
            "m_query_strategy": {
                "connector_type": "Csv.Document",
                "source_expression": "path/to/file.csv",
            },
        }
        table = TableDesign.model_validate(data)
        self.assertEqual(table.name, "T")
        self.assertFalse(table.is_calc_group)


class DaxMeasuresDesignTests(unittest.TestCase):
    """Tests for DaxMeasuresDesign validation."""

    def test_valid_measures(self):
        """A measure list with all three translatability levels validates."""
        measures = _valid_dax_measures(
            measures=[
                _valid_measure(translatability="direct"),
                _valid_measure(
                    caption="Complex Calc",
                    translatability="redesign",
                    target_dax_approach="CALCULATE + ALLEXCEPT",
                ),
                _valid_measure(
                    caption="Running Sum",
                    translatability="manual",
                    target_dax_approach="",
                ),
            ],
        )
        dax = DaxMeasuresDesign.model_validate(measures)
        self.assertEqual(len(dax.measures), 3)

    def test_invalid_translatability_fails(self):
        """An invalid translatability value raises a validation error."""
        with self.assertRaises(ValidationError):
            MeasureDesign.model_validate(
                _valid_measure(translatability="impossible"),
            )

    def test_untranslatable_items(self):
        """Untranslatable items validate correctly."""
        item = UntranslatableItem.model_validate(
            {
                "tableau_name": "[Calc_123]",
                "caption": "Running Total",
                "reason": "Table calculation",
                "suggestion": "Use CALCULATE + FILTER",
            }
        )
        self.assertEqual(item.caption, "Running Total")

    def test_empty_measures_accepted(self):
        """An empty measures list is valid (workbook may have no calcs)."""
        dax = DaxMeasuresDesign.model_validate({"measures": []})
        self.assertEqual(dax.measures, [])

    def test_data_type_int64_normalised_to_integer(self):
        """LLM returning 'int64' is normalised to 'integer'."""
        m = MeasureDesign.model_validate(_valid_measure(data_type="int64"))
        self.assertEqual(m.data_type, "integer")

    def test_data_type_double_normalised_to_real(self):
        """LLM returning 'double' is normalised to 'real'."""
        m = MeasureDesign.model_validate(_valid_measure(data_type="double"))
        self.assertEqual(m.data_type, "real")

    def test_data_type_float64_normalised_to_real(self):
        """LLM returning 'float64' is normalised to 'real'."""
        m = MeasureDesign.model_validate(_valid_measure(data_type="float64"))
        self.assertEqual(m.data_type, "real")

    def test_data_type_text_normalised_to_string(self):
        """LLM returning 'text' is normalised to 'string'."""
        m = MeasureDesign.model_validate(_valid_measure(data_type="text"))
        self.assertEqual(m.data_type, "string")

    def test_data_type_bool_normalised_to_boolean(self):
        """LLM returning 'bool' is normalised to 'boolean'."""
        m = MeasureDesign.model_validate(_valid_measure(data_type="bool"))
        self.assertEqual(m.data_type, "boolean")

    def test_data_type_canonical_values_pass_through(self):
        """All canonical values pass through unchanged."""
        for canonical in ("string", "integer", "real", "boolean", "date", "datetime"):
            m = MeasureDesign.model_validate(_valid_measure(data_type=canonical))
            self.assertEqual(m.data_type, canonical, f"Expected {canonical} to pass through")


class ReportDesignTests(unittest.TestCase):
    """Tests for ReportDesign validation."""

    def test_valid_report(self):
        """A complete report design parses correctly."""
        report = ReportDesign.model_validate(_valid_report())
        self.assertEqual(len(report.pages), 1)
        self.assertEqual(report.pages[0].dashboard_name, "Clienti")

    def test_empty_pages_fails(self):
        """An empty pages list raises a validation error."""
        with self.assertRaises(ValidationError):
            ReportDesign.model_validate(_valid_report(pages=[]))

    def test_page_display_name_defaults(self):
        """Page display_name defaults to dashboard_name when empty."""
        page = PageDesign.model_validate(
            _valid_page(display_name=""),
        )
        self.assertEqual(page.display_name, "Clienti")

    def test_field_binding_kind_literal(self):
        """FieldBinding field_kind must be a valid literal."""
        with self.assertRaises(ValidationError):
            FieldBinding.model_validate(
                _valid_field_binding(field_kind="Invalid"),
            )

    def test_entity_resolution_map(self):
        """EntityResolutionMap validates with lookup data."""
        erm = EntityResolutionMap.model_validate(
            {
                "datasource_to_table": {"fed.123": "Table1"},
                "calculated_field_map": {"Calc_456": "Measure1"},
            }
        )
        self.assertEqual(erm.datasource_to_table["fed.123"], "Table1")

    def test_visual_minimal(self):
        """A visual with only required fields validates."""
        vis = VisualDesign.model_validate(
            {
                "worksheet_name": "Sheet1",
                "visual_type": "barChart",
            }
        )
        self.assertEqual(vis.worksheet_name, "Sheet1")
        self.assertEqual(vis.field_bindings, [])

    def test_slicer_visual_with_slicer_column(self):
        """A slicer visual with slicer_column validates correctly."""
        vis = VisualDesign.model_validate(
            {
                "worksheet_name": "Slicer — Categoria",
                "visual_type": "slicer",
                "title": "Categoria",
                "position": {"x": 10, "y": 5, "width": 200, "height": 40},
                "field_bindings": [_valid_field_binding(field_kind="Column")],
                "slicer_column": "'Ordini'[Categoria]",
                "notes": "From Tableau quick-filter (filter_group 10)",
            }
        )
        self.assertEqual(vis.visual_type, "slicer")
        self.assertEqual(vis.slicer_column, "'Ordini'[Categoria]")

    def test_slicer_column_defaults_empty(self):
        """Non-slicer visuals have empty slicer_column by default."""
        vis = VisualDesign.model_validate(
            {
                "worksheet_name": "Sheet1",
                "visual_type": "barChart",
            }
        )
        self.assertEqual(vis.slicer_column, "")


class MigrationAssessmentTests(unittest.TestCase):
    """Tests for MigrationAssessment validation."""

    def test_valid_assessment(self):
        """A complete assessment parses correctly."""
        assessment = MigrationAssessment.model_validate(
            _valid_assessment(),
        )
        self.assertEqual(assessment.complexity_score, "medium")
        self.assertEqual(len(assessment.warnings), 1)

    def test_default_assessment(self):
        """An empty dict produces valid defaults."""
        assessment = MigrationAssessment.model_validate({})
        self.assertEqual(assessment.complexity_score, "medium")
        self.assertEqual(assessment.warnings, [])
        self.assertEqual(assessment.manual_items, [])

    def test_invalid_complexity_fails(self):
        """An invalid complexity_score raises a validation error."""
        with self.assertRaises(ValidationError):
            MigrationAssessment.model_validate(
                _valid_assessment(complexity_score="extreme"),
            )

    def test_warning_severity_literal(self):
        """Warning severity must be info, warning, or error."""
        with self.assertRaises(ValidationError):
            AssessmentWarning.model_validate(
                {
                    "code": "WARN_TEST",
                    "severity": "critical",
                    "message": "test",
                }
            )


class DataModelDesignTests(unittest.TestCase):
    """Tests for the combined Call 1 output model."""

    def test_valid_data_model(self):
        """A complete Call 1 output validates."""
        dm = DataModelDesign.model_validate(_valid_data_model_design())
        self.assertEqual(len(dm.semantic_model.tables), 1)
        self.assertEqual(len(dm.dax_measures.measures), 1)

    def test_missing_semantic_model_fails(self):
        """Omitting semantic_model raises a validation error."""
        with self.assertRaises(ValidationError):
            DataModelDesign.model_validate(
                {"dax_measures": _valid_dax_measures()},
            )


class TargetTechnicalDocTests(unittest.TestCase):
    """Tests for the root TargetTechnicalDocumentation model."""

    def test_valid_full_tdd(self):
        """A complete TDD validates correctly."""
        tdd = TargetTechnicalDocumentation.model_validate(_valid_tdd())
        self.assertEqual(len(tdd.semantic_model.tables), 1)
        self.assertEqual(len(tdd.dax_measures.measures), 1)
        self.assertEqual(len(tdd.report.pages), 1)
        self.assertEqual(tdd.assessment.complexity_score, "medium")

    def test_json_round_trip(self):
        """TDD serialises to JSON and back without data loss."""
        tdd = TargetTechnicalDocumentation.model_validate(_valid_tdd())
        json_str = tdd.model_dump_json(indent=2)
        reloaded = TargetTechnicalDocumentation.model_validate_json(json_str)
        self.assertEqual(
            tdd.semantic_model.tables[0].name,
            reloaded.semantic_model.tables[0].name,
        )
        self.assertEqual(
            tdd.dax_measures.measures[0].caption,
            reloaded.dax_measures.measures[0].caption,
        )
        self.assertEqual(
            tdd.report.pages[0].dashboard_name,
            reloaded.report.pages[0].dashboard_name,
        )


# ════════════════════════════════════════════════════════════════════════
#  Gap-Fill Model Tests (semantic_role, parameter domain, etc.)
# ════════════════════════════════════════════════════════════════════════


class ColumnSemanticRoleTests(unittest.TestCase):
    """Tests for ColumnDesign.semantic_role."""

    def test_semantic_role_defaults_empty(self):
        col = ColumnDesign.model_validate(_valid_column())
        self.assertEqual(col.semantic_role, "")

    def test_semantic_role_city(self):
        col = ColumnDesign.model_validate(_valid_column(semantic_role="City"))
        self.assertEqual(col.semantic_role, "City")

    def test_semantic_role_state(self):
        col = ColumnDesign.model_validate(
            _valid_column(semantic_role="StateOrProvince"),
        )
        self.assertEqual(col.semantic_role, "StateOrProvince")


class ParameterDomainTests(unittest.TestCase):
    """Tests for ParameterDesign domain fields."""

    def test_domain_defaults_to_all(self):
        p = ParameterDesign.model_validate(_valid_parameter())
        self.assertEqual(p.domain_type, "all")
        self.assertEqual(p.range_min, "")
        self.assertEqual(p.range_max, "")
        self.assertEqual(p.range_granularity, "")
        self.assertEqual(p.allowed_values, [])

    def test_range_domain(self):
        p = ParameterDesign.model_validate(
            _valid_parameter(
                domain_type="range",
                range_min="0",
                range_max="100",
                range_granularity="5",
            )
        )
        self.assertEqual(p.domain_type, "range")
        self.assertEqual(p.range_min, "0")
        self.assertEqual(p.range_max, "100")
        self.assertEqual(p.range_granularity, "5")

    def test_list_domain(self):
        p = ParameterDesign.model_validate(
            _valid_parameter(
                domain_type="list",
                allowed_values=["A", "B", "C"],
            )
        )
        self.assertEqual(p.domain_type, "list")
        self.assertEqual(p.allowed_values, ["A", "B", "C"])

    def test_invalid_domain_type_fails(self):
        with self.assertRaises(ValidationError):
            ParameterDesign.model_validate(
                _valid_parameter(domain_type="open"),
            )


class MeasureHiddenFormatTests(unittest.TestCase):
    """Tests for MeasureDesign.is_hidden and format_string."""

    def test_hidden_defaults_false(self):
        m = MeasureDesign.model_validate(_valid_measure())
        self.assertFalse(m.is_hidden)

    def test_hidden_true(self):
        m = MeasureDesign.model_validate(_valid_measure(is_hidden=True))
        self.assertTrue(m.is_hidden)

    def test_format_string_defaults_empty(self):
        m = MeasureDesign.model_validate(_valid_measure())
        self.assertEqual(m.format_string, "")

    def test_format_string_percentage(self):
        m = MeasureDesign.model_validate(
            _valid_measure(format_string="0.00%"),
        )
        self.assertEqual(m.format_string, "0.00%")


# ════════════════════════════════════════════════════════════════════════
#  Chunked-Batch Tests
# ════════════════════════════════════════════════════════════════════════

# These tests verify the chunked-batch strategy: when a prompt exceeds
# the token budget, the agent splits input into batches, calls the LLM
# per batch (with func_doc in every batch), and merges results
# deterministically.


def _make_tdd_agent():
    """Create a TargetTechnicalDocAgent backed by MockBackend."""
    from Tableau2PowerBI.agents.target_technical_doc import (
        TargetTechnicalDocAgent,
    )
    from Tableau2PowerBI.core.backends import MockBackend
    from Tableau2PowerBI.core.config import AgentSettings

    settings = AgentSettings(project_endpoint="https://example.test")
    agent = TargetTechnicalDocAgent(settings=settings)
    agent.backend = MockBackend()
    agent._backend_initialized = True
    return agent


def _make_tdd_agent_with_budget(budget: int):
    """Create a TargetTechnicalDocAgent with a custom token budget."""
    from Tableau2PowerBI.agents.target_technical_doc import (
        TargetTechnicalDocAgent,
    )
    from Tableau2PowerBI.core.backends import MockBackend
    from Tableau2PowerBI.core.config import AgentSettings

    settings = AgentSettings(
        project_endpoint="https://example.test",
        tdd_max_prompt_tokens=budget,
    )
    agent = TargetTechnicalDocAgent(settings=settings)
    agent.backend = MockBackend()
    agent._backend_initialized = True
    return agent


def _stub_data_model() -> DataModelDesign:
    """Return a valid DataModelDesign for testing."""
    return DataModelDesign.model_validate(_valid_data_model_design())


def _stub_report() -> ReportDesign:
    """Return a valid ReportDesign for testing."""
    return ReportDesign.model_validate(_valid_report())


def _stub_data_model_with_tables(*table_names: str) -> DataModelDesign:
    """Return a DataModelDesign whose tables have the given names."""
    tables = [_valid_table(name=n) for n in table_names]
    return DataModelDesign.model_validate(
        _valid_data_model_design(
            semantic_model=_valid_semantic_model(tables=tables),
        )
    )


class TddCall1SingleBatchTests(unittest.TestCase):
    """Call 1 uses a single LLM call when the prompt fits in context."""

    def test_call1_single_batch_happy_path(self):
        """When full prompt fits in budget, exactly one LLM call is made."""
        agent = _make_tdd_agent_with_budget(1_000_000)
        expected = _stub_data_model()
        call_count = 0

        def _mock_rwv(prompt, model_cls, label):
            nonlocal call_count
            call_count += 1
            return expected

        with patch.object(agent, "_run_with_validation", side_effect=_mock_rwv):
            result = agent._call1_data_model(
                {"datasources": [{"name": "DS1", "tables": []}]},
                {"summary": "small doc"},
            )

        self.assertIs(result, expected)
        self.assertEqual(call_count, 1, "Expected exactly 1 LLM call (no batching)")


class TddCall1ChunkedBatchTests(unittest.TestCase):
    """Call 1 splits into batches when prompt exceeds budget."""

    def test_call1_chunked_two_datasource_batches(self):
        """Two datasources that don't fit together produce two batches,
        each with func_doc included."""
        # Budget of 100 tokens: fixed overhead (~80) + one DS (~16) fits
        # but fixed + two DSs (~112) does not, forcing 2 batches.
        agent = _make_tdd_agent_with_budget(100)
        ds1 = {"name": "DS1", "tables": [{"name": "T1"}] * 3}
        ds2 = {"name": "DS2", "tables": [{"name": "T2"}] * 3}
        sm_input = {"datasources": [ds1, ds2], "parameters": []}
        func_doc = {"summary": "test doc"}

        prompts_seen: list[str] = []
        batch_results = [
            _stub_data_model_with_tables("TableA"),
            _stub_data_model_with_tables("TableB"),
        ]
        call_idx = 0

        def _mock_rwv(prompt, model_cls, label):
            nonlocal call_idx
            prompts_seen.append(prompt)
            result = batch_results[call_idx]
            call_idx += 1
            return result

        with patch.object(agent, "_run_with_validation", side_effect=_mock_rwv):
            result = agent._call1_data_model(sm_input, func_doc)

        self.assertEqual(len(prompts_seen), 2, "Expected 2 batch calls")
        # func_doc must be in EVERY batch prompt
        for i, prompt in enumerate(prompts_seen):
            self.assertIn(
                "Functional Documentation",
                prompt,
                f"Batch {i + 1} prompt missing func_doc",
            )
        # Merged result should contain tables from both batches
        table_names = {t.name for t in result.semantic_model.tables}
        self.assertIn("TableA", table_names)
        self.assertIn("TableB", table_names)

    def test_call1_async_chunked_two_datasource_batches(self):
        """Async Call 1 also splits and includes func_doc in every batch."""
        agent = _make_tdd_agent_with_budget(100)
        ds1 = {"name": "DS1", "tables": [{"name": "T1"}] * 3}
        ds2 = {"name": "DS2", "tables": [{"name": "T2"}] * 3}
        sm_input = {"datasources": [ds1, ds2], "parameters": []}
        func_doc = {"summary": "test doc"}

        prompts_seen: list[str] = []
        batch_results = [
            _stub_data_model_with_tables("AsyncA"),
            _stub_data_model_with_tables("AsyncB"),
        ]
        call_idx = 0

        async def _mock_rwv_async(prompt, model_cls, label):
            nonlocal call_idx
            prompts_seen.append(prompt)
            result = batch_results[call_idx]
            call_idx += 1
            return result

        with patch.object(
            agent, "_run_with_validation_async", side_effect=_mock_rwv_async,
        ):
            result = asyncio.run(
                agent._call1_data_model_async(sm_input, func_doc),
            )

        self.assertEqual(len(prompts_seen), 2)
        for prompt in prompts_seen:
            self.assertIn("Functional Documentation", prompt)
        table_names = {t.name for t in result.semantic_model.tables}
        self.assertIn("AsyncA", table_names)
        self.assertIn("AsyncB", table_names)


class TddCall1MergeTests(unittest.TestCase):
    """Tests for merge_data_model_results deduplication."""

    def test_call1_merge_deduplicates_tables_by_name(self):
        """Tables with the same name across partials keep first occurrence."""
        from Tableau2PowerBI.agents.target_technical_doc.chunking import (
            merge_data_model_results,
        )

        partial1 = DataModelDesign.model_validate(
            _valid_data_model_design(
                semantic_model=_valid_semantic_model(
                    tables=[_valid_table(name="Shared", description="from batch 1")],
                ),
            )
        )
        partial2 = DataModelDesign.model_validate(
            _valid_data_model_design(
                semantic_model=_valid_semantic_model(
                    tables=[
                        _valid_table(name="Shared", description="from batch 2"),
                        _valid_table(name="Unique"),
                    ],
                ),
            )
        )

        merged = merge_data_model_results(
            [partial1, partial2],
            logging.getLogger("test"),
        )

        table_names = [t.name for t in merged.semantic_model.tables]
        self.assertEqual(table_names.count("Shared"), 1, "Shared table should appear once")
        self.assertIn("Unique", table_names)
        # First occurrence wins
        shared_table = next(t for t in merged.semantic_model.tables if t.name == "Shared")
        self.assertEqual(shared_table.description, "from batch 1")


class TddCall2SingleBatchTests(unittest.TestCase):
    """Call 2 uses a single LLM call when the prompt fits in context."""

    def test_call2_single_batch_happy_path(self):
        """When full prompt fits in budget, exactly one LLM call is made."""
        agent = _make_tdd_agent_with_budget(1_000_000)
        expected = _stub_report()
        call_count = 0

        def _mock_rwv(prompt, model_cls, label):
            nonlocal call_count
            call_count += 1
            return expected

        with patch.object(agent, "_run_with_validation", side_effect=_mock_rwv):
            result = agent._call2_report(
                {
                    "dashboards": [{"name": "D1", "sheets": []}],
                    "worksheets": [],
                    "actions": [],
                },
                {"summary": "small doc"},
                _stub_data_model(),
            )

        self.assertIs(result, expected)
        self.assertEqual(call_count, 1, "Expected exactly 1 LLM call (no batching)")


class TddCall2ChunkedBatchTests(unittest.TestCase):
    """Call 2 splits into batches when prompt exceeds budget."""

    def test_call2_chunked_two_dashboard_batches(self):
        """Two dashboards that don't fit together produce two batches,
        each with func_doc included."""
        # Fixed overhead for Call 2 is ~530 tokens (prefix + headers +
        # func_doc + data_model JSON). Shared context is ~16 tokens.
        # Each dashboard + its worksheets is ~35 tokens.
        # Budget of 590: 530 + 16 + 35 = 581 fits one batch, but
        # 530 + 16 + 70 = 616 exceeds 590, forcing 2 batches.
        agent = _make_tdd_agent_with_budget(590)
        ws1 = {"name": "WS1", "type": "worksheet", "fields": ["f"] * 5}
        ws2 = {"name": "WS2", "type": "worksheet", "fields": ["f"] * 5}
        report_input = {
            "dashboards": [
                {"name": "Dash1", "sheets": ["WS1"]},
                {"name": "Dash2", "sheets": ["WS2"]},
            ],
            "worksheets": [ws1, ws2],
            "actions": [],
            "datasource_index": {"ds1": "DS1"},
            "datasources": [{"name": "DS1"}],
        }
        func_doc = {"summary": "test doc"}

        page1 = _valid_page(dashboard_name="Dash1", display_name="Dash1")
        page2 = _valid_page(dashboard_name="Dash2", display_name="Dash2")
        batch_results = [
            ReportDesign.model_validate(
                _valid_report(pages=[page1], standalone_worksheets=[]),
            ),
            ReportDesign.model_validate(
                _valid_report(pages=[page2], standalone_worksheets=[]),
            ),
        ]
        prompts_seen: list[str] = []
        call_idx = 0

        def _mock_rwv(prompt, model_cls, label):
            nonlocal call_idx
            prompts_seen.append(prompt)
            result = batch_results[call_idx]
            call_idx += 1
            return result

        with patch.object(agent, "_run_with_validation", side_effect=_mock_rwv):
            result = agent._call2_report(
                report_input,
                func_doc,
                _stub_data_model(),
            )

        self.assertEqual(len(prompts_seen), 2, "Expected 2 batch calls")
        for i, prompt in enumerate(prompts_seen):
            self.assertIn(
                "Functional Documentation",
                prompt,
                f"Batch {i + 1} prompt missing func_doc",
            )
        # Merged result should have pages from both batches
        self.assertEqual(len(result.pages), 2)


class TddCall2MergeTests(unittest.TestCase):
    """Tests for merge_report_results entity resolution and dedup."""

    def test_call2_entity_resolution_merge_union(self):
        """Different entity_resolution keys across partials are unioned."""
        from Tableau2PowerBI.agents.target_technical_doc.chunking import (
            merge_report_results,
        )

        partial1 = ReportDesign.model_validate(
            _valid_report(
                entity_resolution={
                    "datasource_to_table": {"fed.aaa": "TableA"},
                    "calculated_field_map": {"Calc_1": "Measure1"},
                },
            )
        )
        partial2 = ReportDesign.model_validate(
            _valid_report(
                pages=[_valid_page(dashboard_name="Page2", display_name="Page2")],
                entity_resolution={
                    "datasource_to_table": {"fed.bbb": "TableB"},
                    "calculated_field_map": {"Calc_2": "Measure2"},
                },
            )
        )

        merged = merge_report_results(
            [partial1, partial2],
            logging.getLogger("test"),
        )

        er = merged.entity_resolution
        self.assertIn("fed.aaa", er.datasource_to_table)
        self.assertIn("fed.bbb", er.datasource_to_table)
        self.assertIn("Calc_1", er.calculated_field_map)
        self.assertIn("Calc_2", er.calculated_field_map)

    def test_call2_entity_resolution_conflict_logs_warning(self):
        """Same entity_resolution key with different values logs WARNING."""
        import logging as stdlib_logging
        from Tableau2PowerBI.agents.target_technical_doc.chunking import (
            merge_report_results,
        )

        partial1 = ReportDesign.model_validate(
            _valid_report(
                entity_resolution={
                    "datasource_to_table": {"fed.same": "TableA"},
                    "calculated_field_map": {},
                },
            )
        )
        partial2 = ReportDesign.model_validate(
            _valid_report(
                pages=[_valid_page(dashboard_name="P2", display_name="P2")],
                entity_resolution={
                    "datasource_to_table": {"fed.same": "TableB"},
                    "calculated_field_map": {},
                },
            )
        )

        test_logger = stdlib_logging.getLogger("test.conflict")
        with self.assertLogs(test_logger, level="WARNING") as cm:
            merged = merge_report_results(
                [partial1, partial2],
                test_logger,
            )

        # First value kept
        self.assertEqual(
            merged.entity_resolution.datasource_to_table["fed.same"],
            "TableA",
        )
        # WARNING was logged
        self.assertTrue(
            any("conflict" in msg for msg in cm.output),
            f"Expected a conflict warning in logs, got: {cm.output}",
        )


class TddSingleItemTooLargeTests(unittest.TestCase):
    """When a single datasource/dashboard exceeds the budget, raise."""

    def test_single_item_still_too_large_raises(self):
        """A single datasource that exceeds the budget raises RuntimeError."""
        from Tableau2PowerBI.agents.target_technical_doc.chunking import (
            build_datasource_batches,
        )

        huge_ds = {"name": "Huge", "tables": [{"name": f"T{i}"} for i in range(100)]}
        sm_input = {"datasources": [huge_ds], "parameters": []}

        with self.assertRaises(RuntimeError) as ctx:
            build_datasource_batches(
                sm_input,
                budget_tokens=1,   # impossibly small budget
                fixed_tokens=0,
            )
        self.assertIn("Single datasource", str(ctx.exception))

    def test_single_dashboard_too_large_raises(self):
        """A single dashboard that exceeds the budget raises RuntimeError."""
        from Tableau2PowerBI.agents.target_technical_doc.chunking import (
            build_dashboard_batches,
        )

        huge_db = {"name": "HugeDash", "sheets": [f"WS{i}" for i in range(100)]}
        report_input = {
            "dashboards": [huge_db],
            "worksheets": [{"name": f"WS{i}", "data": "x" * 50} for i in range(100)],
            "actions": [],
            "datasource_index": {},
            "datasources": [],
        }

        with self.assertRaises(RuntimeError) as ctx:
            build_dashboard_batches(
                report_input,
                budget_tokens=1,   # impossibly small budget
                fixed_tokens=0,
            )
        self.assertIn("Single dashboard", str(ctx.exception))


class TddContextLengthFallbackTests(unittest.TestCase):
    """When the single-call path gets ContextLengthExceededError,
    it falls back to the chunked path."""

    def test_call1_context_exceeded_falls_back_to_chunked(self):
        """ContextLengthExceededError on single call triggers batch path."""
        agent = _make_tdd_agent_with_budget(1_000_000)  # large budget so single-call tried first
        expected = _stub_data_model()
        call_count = 0

        def _mock_rwv(prompt, model_cls, label):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ContextLengthExceededError(500_000)
            return expected

        sm_input = {"datasources": [{"name": "DS1", "tables": []}]}
        with patch.object(agent, "_run_with_validation", side_effect=_mock_rwv):
            result = agent._call1_data_model(sm_input, {"summary": "doc"})

        # First call failed, second is the batch call
        self.assertEqual(call_count, 2)
        self.assertIs(result, expected)


# ── Budget-guard tests ────────────────────────────────────────────────


from Tableau2PowerBI.agents.target_technical_doc.chunking import (
    build_datasource_batches,
    build_dashboard_batches,
)


class BuildDatasourceBatchesBudgetTests(unittest.TestCase):
    """Tests for build_datasource_batches budget-guard behaviour."""

    def _one_datasource(self, name: str = "DS1") -> dict:
        """Minimal sm_input with one datasource."""
        return {"datasources": [{"name": name, "tables": []}], "parameters": []}

    def test_build_datasource_batches_raises_when_fixed_exceeds_budget(self):
        """fixed_tokens > budget_tokens must raise RuntimeError with clear numbers.

        The message must contain both the budget value and the fixed value so
        the caller can diagnose the problem.  It must NOT contain a negative
        number as the 'budget allows only ~X' figure.
        """
        budget = 100_000
        fixed = 1_011_741
        with self.assertRaises(RuntimeError) as ctx:
            build_datasource_batches(self._one_datasource(), budget, fixed)

        msg = str(ctx.exception)
        # Message should not show a negative "budget allows" figure
        self.assertNotRegex(
            msg,
            r"allows only ~-\d+",
            "Error message must not expose a negative available-tokens value",
        )

    def test_build_datasource_batches_raises_when_budget_equals_fixed(self):
        """budget_tokens == fixed_tokens leaves zero available; must raise RuntimeError."""
        budget = 50_000
        with self.assertRaises(RuntimeError):
            build_datasource_batches(self._one_datasource(), budget, budget)

    def test_build_datasource_batches_happy_path_unchanged(self):
        """Two small datasources with a healthy budget should return one batch."""
        sm_input = {
            "datasources": [
                {"name": "DS1", "tables": []},
                {"name": "DS2", "tables": []},
            ],
            "parameters": [{"name": "P1", "value": "v"}],
        }
        batches = build_datasource_batches(sm_input, budget_tokens=100_000, fixed_tokens=1_000)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]["datasources"]), 2)
        self.assertIn("parameters", batches[0])

    def test_unusable_budget_error_distinct_from_single_item_error(self):
        """RuntimeError for unusable budget differs from 'Cannot split further' message."""
        budget = 100_000
        fixed = 1_011_741
        with self.assertRaises(RuntimeError) as ctx:
            build_datasource_batches(self._one_datasource(), budget, fixed)

        msg = str(ctx.exception)
        # The existing single-item error ends with "Cannot split further."
        # The new unusable-budget error must NOT be that message.
        self.assertNotIn(
            "Cannot split further",
            msg,
            "Unusable-budget error must be distinct from single-item-too-large error",
        )


class BuildDashboardBatchesBudgetTests(unittest.TestCase):
    """Tests for build_dashboard_batches budget-guard behaviour."""

    def _one_dashboard(self, name: str = "Dashboard1") -> dict:
        """Minimal report_input with one dashboard."""
        return {
            "dashboards": [{"name": name, "sheets": []}],
            "worksheets": [],
            "actions": [],
            "datasource_index": {},
            "datasources": [],
            "standalone_worksheets": [],
        }

    def test_build_dashboard_batches_raises_when_fixed_exceeds_budget(self):
        """fixed_tokens > budget_tokens must raise RuntimeError with non-negative diagnostic."""
        budget = 100_000
        fixed = 1_011_741
        with self.assertRaises(RuntimeError) as ctx:
            build_dashboard_batches(self._one_dashboard(), budget, fixed)

        msg = str(ctx.exception)
        self.assertNotRegex(
            msg,
            r"allows only ~-\d+",
            "Error message must not expose a negative available-tokens value",
        )

    def test_build_dashboard_batches_raises_when_budget_equals_fixed(self):
        """budget_tokens == fixed_tokens leaves zero available; must raise RuntimeError."""
        budget = 50_000
        with self.assertRaises(RuntimeError):
            build_dashboard_batches(self._one_dashboard(), budget, budget)


# ── TDD PromptBudgetError exception-type tests ────────────────────────


class TddBudgetExceptionTypeTests(unittest.TestCase):
    """Tests that budget-guard errors use the PromptBudgetError subclass."""

    def _one_datasource(self, name: str = "DS1") -> dict:
        return {"datasources": [{"name": name, "tables": []}], "parameters": []}

    def _one_dashboard(self, name: str = "Dashboard1") -> dict:
        return {
            "dashboards": [{"name": name, "sheets": []}],
            "worksheets": [],
            "actions": [],
            "datasource_index": {},
            "datasources": [],
            "standalone_worksheets": [],
        }

    def test_build_datasource_batches_raises_prompt_budget_error_when_fixed_exceeds_budget(self):
        """Given a budget of 1000 and fixed_tokens of 2000, when build_datasource_batches
        is called, then it raises PromptBudgetError (a RuntimeError subclass) with a message
        naming both token counts.
        """
        from Tableau2PowerBI.agents.target_technical_doc.chunking import PromptBudgetError

        budget = 1_000
        fixed = 2_000
        with self.assertRaises(PromptBudgetError) as ctx:
            build_datasource_batches(self._one_datasource(), budget, fixed)

        self.assertIsInstance(ctx.exception, RuntimeError,
                              "PromptBudgetError must be a RuntimeError subclass")
        msg = str(ctx.exception)
        self.assertIn(str(budget), msg, "Error message must name the budget token count")
        self.assertIn(str(fixed), msg, "Error message must name the fixed token count")

    def test_build_dashboard_batches_raises_prompt_budget_error_when_fixed_exceeds_budget(self):
        """Given a budget of 1000 and fixed_tokens of 5000, when build_dashboard_batches
        is called, then it raises PromptBudgetError with an actionable message.
        """
        from Tableau2PowerBI.agents.target_technical_doc.chunking import PromptBudgetError

        budget = 1_000
        fixed = 5_000
        with self.assertRaises(PromptBudgetError) as ctx:
            build_dashboard_batches(self._one_dashboard(), budget, fixed)

        self.assertIsInstance(ctx.exception, RuntimeError,
                              "PromptBudgetError must be a RuntimeError subclass")
        msg = str(ctx.exception)
        # Message should contain at least one of the token counts for actionability
        self.assertTrue(
            str(budget) in msg or str(fixed) in msg,
            f"Error message must name the budget or fixed token count; got: {msg!r}",
        )

    def test_build_datasource_batches_single_item_too_large_still_raises_plain_runtimeerror(self):
        """Given fixed_tokens within budget but one datasource alone exceeding available tokens,
        when build_datasource_batches is called, then it raises RuntimeError that is NOT a
        PromptBudgetError.
        """
        from Tableau2PowerBI.agents.target_technical_doc.chunking import PromptBudgetError

        # budget=1, fixed=0 so available=1 token — tiny but not unusable (available > 0)
        # Any real datasource JSON will exceed 1 token, triggering the single-item check
        huge_ds = {"name": "HugeDS", "tables": [{"name": f"T{i}"} for i in range(50)]}
        sm_input = {"datasources": [huge_ds], "parameters": []}

        with self.assertRaises(RuntimeError) as ctx:
            build_datasource_batches(sm_input, budget_tokens=1, fixed_tokens=0)

        exc = ctx.exception
        # Must be a RuntimeError but NOT a PromptBudgetError
        self.assertNotIsInstance(exc, PromptBudgetError,
                                 "Single-item-too-large error must NOT be a PromptBudgetError")
        self.assertIn("Cannot split further", str(exc))


# ── TDD PromptBudgetError fallback-to-single-call tests ──────────────


class TddPromptBudgetFallbackTests(unittest.TestCase):
    """When chunking raises PromptBudgetError, agent falls back to a single call."""

    def setUp(self):
        # Imported here so the module-level ImportError (before production code exists)
        # surfaces as per-test ERRORS rather than a collection failure.
        from Tableau2PowerBI.agents.target_technical_doc.chunking import (
            PromptBudgetError,
        )
        self.PromptBudgetError = PromptBudgetError

    def _make_agent(self, budget: int = 1):
        """Create an agent with a tiny budget so prompt_tokens always exceeds it."""
        return _make_tdd_agent_with_budget(budget)

    def _minimal_sm_input(self) -> dict:
        return {"datasources": [{"name": "DS1", "tables": []}], "parameters": []}

    def _minimal_report_input(self) -> dict:
        return {
            "dashboards": [{"name": "Dash1", "sheets": []}],
            "worksheets": [],
            "actions": [],
            "datasource_index": {},
            "datasources": [],
            "standalone_worksheets": [],
        }

    def test_call1_falls_back_to_single_call_when_prompt_budget_error_raised(self):
        """Given a Call 1 prompt exceeding budget with fixed_tokens forcing PromptBudgetError
        during chunking, when _call1_data_model runs, then _run_with_validation is invoked
        with the original full prompt and the result is returned.

        Given: budget=1 so prompt_tokens > budget (chunked path entered)
               build_datasource_batches raises PromptBudgetError
        When:  _call1_data_model is called
        Then:  _run_with_validation called once with the full prompt string, result returned
        """
        agent = self._make_agent(budget=1)
        expected = _stub_data_model()

        with patch(
            "Tableau2PowerBI.agents.target_technical_doc.build_datasource_batches",
            side_effect=self.PromptBudgetError("fixed overhead too large"),
        ):
            with patch.object(agent, "_run_with_validation", return_value=expected) as mock_rwv:
                result = agent._call1_data_model(self._minimal_sm_input(), None)

        mock_rwv.assert_called_once()
        call_args = mock_rwv.call_args[0]
        self.assertIsInstance(call_args[0], str, "First arg must be the full prompt string")
        self.assertIs(result, expected)

    def test_call1_async_falls_back_to_single_call_when_prompt_budget_error_raised(self):
        """Given the async Call 1 path with fixed_tokens > budget, when _call1_data_model_async
        runs, then _run_with_validation_async is awaited once with the original full prompt.

        Given: budget=1, build_datasource_batches raises PromptBudgetError
        When:  _call1_data_model_async is awaited
        Then:  _run_with_validation_async awaited once with full prompt str
        """
        agent = self._make_agent(budget=1)
        expected = _stub_data_model()

        async def _run():
            with patch(
                "Tableau2PowerBI.agents.target_technical_doc.build_datasource_batches",
                side_effect=self.PromptBudgetError("fixed overhead too large"),
            ):
                with patch.object(
                    agent, "_run_with_validation_async", return_value=expected,
                ) as mock_rwva:
                    result = await agent._call1_data_model_async(self._minimal_sm_input(), None)

            mock_rwva.assert_called_once()
            call_args = mock_rwva.call_args[0]
            self.assertIsInstance(call_args[0], str)
            self.assertIs(result, expected)

        asyncio.run(_run())

    def test_call2_falls_back_to_single_call_when_prompt_budget_error_raised(self):
        """Given a Call 2 setup where fixed_tokens > budget, when _call2_report runs,
        then _run_with_validation is invoked once with the full Call 2 prompt.

        Given: budget=1, build_dashboard_batches raises PromptBudgetError
        When:  _call2_report is called
        Then:  _run_with_validation called once with full prompt string
        """
        agent = self._make_agent(budget=1)
        expected = _stub_report()

        with patch(
            "Tableau2PowerBI.agents.target_technical_doc.build_dashboard_batches",
            side_effect=self.PromptBudgetError("dashboard overhead too large"),
        ):
            with patch.object(agent, "_run_with_validation", return_value=expected) as mock_rwv:
                result = agent._call2_report(
                    self._minimal_report_input(), None, _stub_data_model(),
                )

        mock_rwv.assert_called_once()
        call_args = mock_rwv.call_args[0]
        self.assertIsInstance(call_args[0], str)
        self.assertIs(result, expected)

    def test_call2_async_falls_back_to_single_call_when_prompt_budget_error_raised(self):
        """Given the async Call 2 path with fixed_tokens > budget, when _call2_report_async
        runs, then _run_with_validation_async is awaited once with the full Call 2 prompt.

        Given: budget=1, build_dashboard_batches raises PromptBudgetError
        When:  _call2_report_async is awaited
        Then:  _run_with_validation_async awaited once with full prompt str
        """
        agent = self._make_agent(budget=1)
        expected = _stub_report()

        async def _run():
            with patch(
                "Tableau2PowerBI.agents.target_technical_doc.build_dashboard_batches",
                side_effect=self.PromptBudgetError("dashboard overhead too large"),
            ):
                with patch.object(
                    agent, "_run_with_validation_async", return_value=expected,
                ) as mock_rwva:
                    result = await agent._call2_report_async(
                        self._minimal_report_input(), None, _stub_data_model(),
                    )

            mock_rwva.assert_called_once()
            call_args = mock_rwva.call_args[0]
            self.assertIsInstance(call_args[0], str)
            self.assertIs(result, expected)

        asyncio.run(_run())

    def test_call1_fallback_logs_warning_naming_fallback_and_single_call(self):
        """Given Call 1 hitting PromptBudgetError, when the fallback path executes,
        then a WARNING log is emitted containing 'fallback' and 'single call'.

        Given: budget=1, PromptBudgetError during chunking
        When:  _call1_data_model runs
        Then:  WARNING log contains 'fallback' and 'single call' (case-insensitive)
        """
        agent = self._make_agent(budget=1)
        expected = _stub_data_model()

        with patch(
            "Tableau2PowerBI.agents.target_technical_doc.build_datasource_batches",
            side_effect=self.PromptBudgetError("overhead too large"),
        ):
            with patch.object(agent, "_run_with_validation", return_value=expected):
                with self.assertLogs("Tableau2PowerBI", level="WARNING") as cm:
                    agent._call1_data_model(self._minimal_sm_input(), None)

        output_lower = " ".join(cm.output).lower()
        self.assertIn("fallback", output_lower,
                      f"Expected 'fallback' in WARNING logs; got: {cm.output}")
        self.assertIn("single call", output_lower,
                      f"Expected 'single call' in WARNING logs; got: {cm.output}")

    def test_call1_fallback_surfaces_context_length_error_when_single_call_too_large(self):
        """Given the fallback single call raising ContextLengthExceededError, when
        _call1_data_model runs, then that exception propagates to the caller unchanged.

        Given: budget=1, PromptBudgetError during chunking
               fallback single call raises ContextLengthExceededError
        When:  _call1_data_model runs
        Then:  ContextLengthExceededError propagates unchanged
        """
        agent = self._make_agent(budget=1)

        with patch(
            "Tableau2PowerBI.agents.target_technical_doc.build_datasource_batches",
            side_effect=self.PromptBudgetError("overhead too large"),
        ):
            with patch.object(
                agent,
                "_run_with_validation",
                side_effect=ContextLengthExceededError(200_000),
            ):
                with self.assertRaises(ContextLengthExceededError):
                    agent._call1_data_model(self._minimal_sm_input(), None)

    def test_single_item_too_large_runtimeerror_not_swallowed_by_fallback(self):
        """Given a plain RuntimeError (not PromptBudgetError) raised during chunking
        (single datasource too large), when _call1_data_model runs, then the RuntimeError
        propagates and no fallback single call is attempted.

        Given: budget=1, build_datasource_batches raises plain RuntimeError (single-item)
        When:  _call1_data_model runs
        Then:  RuntimeError propagates; _run_with_validation NOT called
        """
        agent = self._make_agent(budget=1)
        plain_error = RuntimeError("Single datasource 'DS1' ... Cannot split further.")

        with patch(
            "Tableau2PowerBI.agents.target_technical_doc.build_datasource_batches",
            side_effect=plain_error,
        ):
            with patch.object(agent, "_run_with_validation") as mock_rwv:
                with self.assertRaises(RuntimeError) as ctx:
                    agent._call1_data_model(self._minimal_sm_input(), None)

        # The plain RuntimeError should propagate, not be swallowed
        self.assertIs(ctx.exception, plain_error)
        mock_rwv.assert_not_called()
