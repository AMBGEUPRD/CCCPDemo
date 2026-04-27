"""Sort, interaction, and renderer tests for the target technical doc agent."""

import unittest

from pydantic import ValidationError

from Tableau2PowerBI.agents.target_technical_doc.models import (
    FieldBinding,
    InteractionDesign,
    PageDesign,
    ReferenceLineSpec,
    SortSpec,
    TargetTechnicalDocumentation,
    VisualDesign,
)
from Tableau2PowerBI.agents.target_technical_doc.renderer import (
    render_html,
    render_markdown,
)


def _valid_column(**overrides) -> dict:
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
    base = {
        "connector_type": "Excel.Workbook",
        "source_expression": 'DataFolderPath & "\\Data\\file.xlsx"',
        "navigation_steps": ['Source{[Name="Ordini"]}[Data]'],
        "notes": "",
    }
    base.update(overrides)
    return base


def _valid_table(**overrides) -> dict:
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
    base = {
        "tables": [_valid_table()],
        "relationships": [_valid_relationship()],
        "parameters": [_valid_parameter()],
        "source_query_culture": "it-IT",
    }
    base.update(overrides)
    return base


def _valid_measure(**overrides) -> dict:
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
    base = {
        "measures": [_valid_measure()],
        "untranslatable": [],
    }
    base.update(overrides)
    return base


def _valid_field_binding(**overrides) -> dict:
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
    base = {
        "semantic_model": _valid_semantic_model(),
        "dax_measures": _valid_dax_measures(),
        "report": _valid_report(),
        "assessment": _valid_assessment(),
    }
    base.update(overrides)
    return base


class FieldBindingWellTests(unittest.TestCase):
    """Tests for FieldBinding.well."""

    def test_well_defaults_empty(self):
        fb = FieldBinding.model_validate(_valid_field_binding())
        self.assertEqual(fb.well, "")

    def test_well_category(self):
        fb = FieldBinding.model_validate(
            _valid_field_binding(well="Category"),
        )
        self.assertEqual(fb.well, "Category")

    def test_well_values(self):
        fb = FieldBinding.model_validate(
            _valid_field_binding(well="Values"),
        )
        self.assertEqual(fb.well, "Values")

    def test_well_tooltips(self):
        fb = FieldBinding.model_validate(
            _valid_field_binding(well="Tooltips"),
        )
        self.assertEqual(fb.well, "Tooltips")


class SortSpecTests(unittest.TestCase):
    """Tests for SortSpec model."""

    def test_valid_sort_spec(self):
        ss = SortSpec.model_validate(
            {
                "field": "Vendite",
                "direction": "DESC",
                "sort_type": "computed",
            }
        )
        self.assertEqual(ss.field, "Vendite")
        self.assertEqual(ss.direction, "DESC")
        self.assertEqual(ss.sort_type, "computed")

    def test_sort_spec_defaults(self):
        ss = SortSpec.model_validate({"field": "Name"})
        self.assertEqual(ss.direction, "ASC")
        self.assertEqual(ss.sort_type, "field")

    def test_invalid_direction_fails(self):
        with self.assertRaises(ValidationError):
            SortSpec.model_validate(
                {
                    "field": "X",
                    "direction": "ASCENDING",
                }
            )

    def test_invalid_sort_type_fails(self):
        with self.assertRaises(ValidationError):
            SortSpec.model_validate(
                {
                    "field": "X",
                    "sort_type": "alphabetical",
                }
            )


class ReferenceLineSpecTests(unittest.TestCase):
    """Tests for ReferenceLineSpec model."""

    def test_valid_reference_line(self):
        rl = ReferenceLineSpec.model_validate(
            {
                "line_type": "average",
                "field": "Vendite",
                "label": "Avg Sales",
            }
        )
        self.assertEqual(rl.line_type, "average")
        self.assertEqual(rl.field, "Vendite")

    def test_defaults(self):
        rl = ReferenceLineSpec.model_validate({})
        self.assertEqual(rl.line_type, "average")
        self.assertEqual(rl.field, "")
        self.assertEqual(rl.label, "")

    def test_invalid_line_type_fails(self):
        with self.assertRaises(ValidationError):
            ReferenceLineSpec.model_validate({"line_type": "trend"})


class InteractionDesignTests(unittest.TestCase):
    """Tests for InteractionDesign model."""

    def test_valid_interaction(self):
        ia = InteractionDesign.model_validate(
            {
                "action_name": "Action11",
                "interaction_type": "crossFilter",
                "source_visual": "Dispersione cliente",
                "target_fields": ["'Ordini'[Regione]"],
            }
        )
        self.assertEqual(ia.action_name, "Action11")
        self.assertEqual(ia.interaction_type, "crossFilter")

    def test_defaults(self):
        ia = InteractionDesign.model_validate({"action_name": "A1"})
        self.assertEqual(ia.interaction_type, "crossFilter")
        self.assertEqual(ia.source_visual, "")
        self.assertEqual(ia.target_fields, [])

    def test_invalid_interaction_type_fails(self):
        with self.assertRaises(ValidationError):
            InteractionDesign.model_validate(
                {
                    "action_name": "A1",
                    "interaction_type": "navigate",
                }
            )


class VisualSortRefLineTests(unittest.TestCase):
    """Tests for VisualDesign sort_specs, reference_lines, display_title."""

    def test_sort_specs_default_empty(self):
        vis = VisualDesign.model_validate(_valid_visual())
        self.assertEqual(vis.sort_specs, [])

    def test_sort_specs_populated(self):
        vis = VisualDesign.model_validate(
            _valid_visual(
                sort_specs=[{"field": "Vendite", "direction": "DESC", "sort_type": "field"}],
            )
        )
        self.assertEqual(len(vis.sort_specs), 1)
        self.assertEqual(vis.sort_specs[0].direction, "DESC")

    def test_reference_lines_default_empty(self):
        vis = VisualDesign.model_validate(_valid_visual())
        self.assertEqual(vis.reference_lines, [])

    def test_reference_lines_populated(self):
        vis = VisualDesign.model_validate(
            _valid_visual(
                reference_lines=[{"line_type": "median", "field": "Profitto"}],
            )
        )
        self.assertEqual(len(vis.reference_lines), 1)
        self.assertEqual(vis.reference_lines[0].line_type, "median")

    def test_display_title_default_empty(self):
        vis = VisualDesign.model_validate(_valid_visual())
        self.assertEqual(vis.display_title, "")

    def test_display_title_set(self):
        vis = VisualDesign.model_validate(
            _valid_visual(display_title="Classificazione clienti"),
        )
        self.assertEqual(vis.display_title, "Classificazione clienti")


class PageInteractionsTests(unittest.TestCase):
    """Tests for PageDesign page_order and interactions."""

    def test_page_order_default_zero(self):
        page = PageDesign.model_validate(_valid_page())
        self.assertEqual(page.page_order, 0)

    def test_page_order_set(self):
        page = PageDesign.model_validate(_valid_page(page_order=3))
        self.assertEqual(page.page_order, 3)

    def test_interactions_default_empty(self):
        page = PageDesign.model_validate(_valid_page())
        self.assertEqual(page.interactions, [])

    def test_interactions_populated(self):
        page = PageDesign.model_validate(
            _valid_page(
                interactions=[
                    {
                        "action_name": "Action11",
                        "interaction_type": "highlight",
                        "source_visual": "Sheet1",
                    }
                ],
            )
        )
        self.assertEqual(len(page.interactions), 1)
        self.assertEqual(page.interactions[0].interaction_type, "highlight")


class MarkdownRendererTests(unittest.TestCase):
    """Test the deterministic Markdown renderer."""

    def setUp(self):
        self.tdd = TargetTechnicalDocumentation.model_validate(
            _valid_tdd(),
        )
        self.md = render_markdown(self.tdd)

    def test_title_is_h1(self):
        self.assertIn("# Target Technical Documentation", self.md)

    def test_assessment_section(self):
        self.assertIn("## Migration Assessment", self.md)
        self.assertIn("**Complexity:** medium", self.md)

    def test_warnings_table(self):
        self.assertIn("| `WARN_TABLE_CALC`", self.md)

    def test_semantic_model_section(self):
        self.assertIn("## Semantic Model Design", self.md)
        self.assertIn("#### Ordini", self.md)

    def test_column_table(self):
        self.assertIn("| Vendite |", self.md)
        self.assertIn("| `double`", self.md)

    def test_relationships_table(self):
        self.assertIn("### Relationships", self.md)
        self.assertIn("Ordini.ID cliente", self.md)

    def test_dax_section(self):
        self.assertIn("## DAX Measures Design", self.md)
        self.assertIn("### Direct Translation", self.md)
        self.assertIn("Rapporto profitto", self.md)

    def test_report_section(self):
        self.assertIn("## Report Design", self.md)
        self.assertIn("### Page: Clienti", self.md)

    def test_visual_details(self):
        self.assertIn("`scatterChart`", self.md)
        self.assertIn("| [Vendite] |", self.md)

    def test_standalone_worksheets(self):
        self.assertIn("### Standalone Worksheets", self.md)
        self.assertIn("- Rapporto profitto per citta", self.md)

    def test_entity_resolution_map(self):
        self.assertIn("### Entity Resolution Map", self.md)
        self.assertIn("federated.0hgpf0j1fdpvv316shikk0mmdlec", self.md)


class HtmlRendererTests(unittest.TestCase):
    """Test the deterministic HTML renderer."""

    def setUp(self):
        self.tdd = TargetTechnicalDocumentation.model_validate(
            _valid_tdd(),
        )
        self.html = render_html(self.tdd)

    def test_valid_html_structure(self):
        self.assertIn("<!DOCTYPE html>", self.html)
        self.assertIn("<html", self.html)
        self.assertIn("</html>", self.html)

    def test_title_in_head(self):
        self.assertIn(
            "<title>Target Technical Documentation</title>",
            self.html,
        )

    def test_toc_has_sections(self):
        self.assertIn('href="#assessment"', self.html)
        self.assertIn('href="#semantic-model"', self.html)
        self.assertIn('href="#dax-measures"', self.html)
        self.assertIn('href="#report"', self.html)

    def test_table_names_in_toc(self):
        self.assertIn('href="#tbl-ordini"', self.html)

    def test_collapsible_sections(self):
        self.assertIn("<details", self.html)
        self.assertIn("<summary>", self.html)

    def test_badge_elements(self):
        self.assertIn('class="badge"', self.html)

    def test_self_contained_styles(self):
        self.assertIn("<style>", self.html)
        self.assertNotIn('rel="stylesheet"', self.html)

    def test_assessment_section(self):
        self.assertIn('id="assessment"', self.html)
        self.assertIn("WARN_TABLE_CALC", self.html)

    def test_semantic_model_section(self):
        self.assertIn('id="semantic-model"', self.html)
        self.assertIn("Ordini", self.html)


if __name__ == "__main__":
    unittest.main()
