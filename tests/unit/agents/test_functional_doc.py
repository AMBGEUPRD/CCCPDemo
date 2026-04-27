"""Tests for the Functional Documentation Agent.

Covers: Pydantic model validation, response parsing, Markdown rendering,
HTML rendering, and edge cases — all without LLM calls.
"""

import json
import logging
import unittest

from pydantic import ValidationError

from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.agents.functional_doc.models import (
    CrossCuttingInsights,
    FieldDescription,
    FunctionalDocumentation,
)
from Tableau2PowerBI.agents.functional_doc.renderer import (
    render_html,
    render_markdown,
)
from tests.support import managed_tempdir

# ── Helpers ───────────────────────────────────────────────────────────


def _valid_field(**overrides) -> dict:
    """Build a valid FieldDescription dict."""
    base = {"name": "Sales", "description": "Total revenue"}
    base.update(overrides)
    return base


def _valid_worksheet(**overrides) -> dict:
    """Build a valid WorksheetDoc dict."""
    base = {
        "name": "Sales by Region",
        "purpose": "Shows sales broken down by region",
        "visualization_type": "bar",
        "metrics_shown": ["Sales", "Profit"],
        "dimensions_used": ["Region"],
        "filters_explained": ["Year filter applied"],
        "interactivity": "Click to filter by region",
        "calculated_fields_explained": [_valid_field()],
        "business_interpretation": "Higher regions need attention",
    }
    base.update(overrides)
    return base


def _valid_dashboard(**overrides) -> dict:
    """Build a valid DashboardDoc dict."""
    base = {
        "name": "Overview",
        "purpose": "Executive summary of sales performance",
        "target_audience": "Leadership",
        "key_insights": ["Revenue grew 10%", "West region leads"],
        "worksheets": [_valid_worksheet()],
    }
    base.update(overrides)
    return base


def _valid_datasource(**overrides) -> dict:
    """Build a valid DataSourceDoc dict."""
    base = {
        "name": "Sales Data",
        "purpose": "Core transactional sales data",
        "key_fields": [_valid_field()],
        "relationships_explained": "Joined to Products on ID",
    }
    base.update(overrides)
    return base


def _valid_parameter(**overrides) -> dict:
    """Build a valid ParameterDoc dict."""
    base = {
        "name": "Target Quota",
        "purpose": "Sets the sales target threshold",
        "business_impact": "Changes quota attainment calculations",
        "usage_context": "Used in the Commission dashboard",
    }
    base.update(overrides)
    return base


def _valid_doc(**overrides) -> dict:
    """Build a valid FunctionalDocumentation dict."""
    base = {
        "workbook_summary": {
            "title": "Sales Analysis",
            "purpose": "Comprehensive sales analytics workbook",
            "target_audience": "Sales managers",
            "key_business_questions": [
                "What are the top selling products?",
                "Which regions underperform?",
            ],
        },
        "data_sources": [_valid_datasource()],
        "dashboards": [_valid_dashboard()],
        "standalone_worksheets": [_valid_worksheet(name="Standalone Sheet")],
        "parameters": [_valid_parameter()],
        "cross_cutting_insights": {
            "data_lineage_summary": "Data flows from Excel to the model.",
            "interactivity_patterns": "Filters cascade across dashboards.",
            "limitations_and_notes": "Locale is Italian.",
        },
    }
    base.update(overrides)
    return base


# ════════════════════════════════════════════════════════════════════════
#  Model Validation Tests
# ════════════════════════════════════════════════════════════════════════


class ModelValidationTests(unittest.TestCase):
    """Test Pydantic model validation for the documentation schema."""

    def test_valid_full_document(self):
        """A complete valid dict parses without errors."""
        doc = FunctionalDocumentation.model_validate(_valid_doc())
        self.assertEqual(doc.workbook_summary.title, "Sales Analysis")
        self.assertEqual(len(doc.dashboards), 1)
        self.assertEqual(len(doc.standalone_worksheets), 1)
        self.assertEqual(len(doc.parameters), 1)

    def test_minimal_document(self):
        """A document with only the required workbook_summary parses."""
        data = {
            "workbook_summary": {
                "title": "Minimal",
                "purpose": "Test",
            }
        }
        doc = FunctionalDocumentation.model_validate(data)
        self.assertEqual(doc.workbook_summary.title, "Minimal")
        self.assertEqual(doc.dashboards, [])
        self.assertEqual(doc.standalone_worksheets, [])
        self.assertEqual(doc.parameters, [])

    def test_missing_workbook_summary_fails(self):
        """Omitting workbook_summary raises a validation error."""
        with self.assertRaises(ValidationError):
            FunctionalDocumentation.model_validate({"dashboards": []})

    def test_missing_title_fails(self):
        """workbook_summary without title raises a validation error."""
        with self.assertRaises(ValidationError):
            FunctionalDocumentation.model_validate({"workbook_summary": {"purpose": "Test"}})

    def test_empty_lists_accepted(self):
        """Empty lists for optional collections are valid."""
        data = _valid_doc(
            dashboards=[],
            standalone_worksheets=[],
            parameters=[],
            data_sources=[],
        )
        doc = FunctionalDocumentation.model_validate(data)
        self.assertEqual(doc.dashboards, [])

    def test_dashboard_with_no_worksheets(self):
        """A dashboard with zero worksheets is valid (lenient schema)."""
        dash = _valid_dashboard(worksheets=[])
        data = _valid_doc(dashboards=[dash])
        doc = FunctionalDocumentation.model_validate(data)
        self.assertEqual(doc.dashboards[0].worksheets, [])

    def test_worksheet_optional_fields(self):
        """A worksheet with only the required 'name' field parses."""
        ws = {"name": "Sheet1"}
        doc_data = _valid_doc(
            standalone_worksheets=[ws],
            dashboards=[],
        )
        doc = FunctionalDocumentation.model_validate(doc_data)
        self.assertEqual(
            doc.standalone_worksheets[0].visualization_type,
            "",
        )

    def test_field_description_requires_name(self):
        """FieldDescription must have a 'name'."""
        with self.assertRaises(ValidationError):
            FieldDescription.model_validate(
                {"description": "No name field"},
            )

    def test_cross_cutting_defaults(self):
        """CrossCuttingInsights defaults all fields to empty string."""
        cci = CrossCuttingInsights.model_validate({})
        self.assertEqual(cci.data_lineage_summary, "")
        self.assertEqual(cci.interactivity_patterns, "")
        self.assertEqual(cci.limitations_and_notes, "")


# ════════════════════════════════════════════════════════════════════════
#  Markdown Renderer Tests
# ════════════════════════════════════════════════════════════════════════


class MarkdownRendererTests(unittest.TestCase):
    """Test the deterministic Markdown renderer."""

    def setUp(self):
        self.doc = FunctionalDocumentation.model_validate(_valid_doc())
        self.md = render_markdown(self.doc)

    def test_title_is_h1(self):
        """Workbook title appears as an H1 heading."""
        self.assertIn("# Sales Analysis", self.md)

    def test_purpose_appears(self):
        """Workbook purpose appears in the output."""
        self.assertIn("Comprehensive sales analytics workbook", self.md)

    def test_business_questions_listed(self):
        """Key business questions render as bullet points."""
        self.assertIn("- What are the top selling products?", self.md)
        self.assertIn("- Which regions underperform?", self.md)

    def test_data_sources_section(self):
        """Data Sources section with table headers appears."""
        self.assertIn("## Data Sources", self.md)
        self.assertIn("### Sales Data", self.md)
        self.assertIn("| Field | Description |", self.md)

    def test_dashboards_section(self):
        """Dashboards section is present with nested worksheets."""
        self.assertIn("## Dashboards", self.md)
        self.assertIn("### Overview", self.md)
        self.assertIn("#### Sales by Region", self.md)

    def test_standalone_worksheets_section(self):
        """Standalone worksheets section appears at the right level."""
        self.assertIn("## Standalone Worksheets", self.md)
        self.assertIn("### Standalone Sheet", self.md)

    def test_parameters_table(self):
        """Parameters render as a Markdown table."""
        self.assertIn("## Parameters", self.md)
        self.assertIn("| Target Quota |", self.md)

    def test_cross_cutting_section(self):
        """Cross-cutting insights section is present."""
        self.assertIn("## Cross-Cutting Insights", self.md)
        self.assertIn("### Data Lineage", self.md)

    def test_minimal_doc_renders(self):
        """A minimal document (only summary) renders without errors."""
        minimal = FunctionalDocumentation.model_validate(
            {
                "workbook_summary": {"title": "Minimal", "purpose": "Test"},
            }
        )
        md = render_markdown(minimal)
        self.assertIn("# Minimal", md)
        # No dashboards section
        self.assertNotIn("## Dashboards", md)

    def test_no_empty_sections(self):
        """Empty optional sections are omitted from the output."""
        data = _valid_doc(
            dashboards=[],
            standalone_worksheets=[],
            parameters=[],
        )
        doc = FunctionalDocumentation.model_validate(data)
        md = render_markdown(doc)
        self.assertNotIn("## Dashboards", md)
        self.assertNotIn("## Standalone Worksheets", md)
        self.assertNotIn("## Parameters", md)


# ════════════════════════════════════════════════════════════════════════
#  HTML Renderer Tests
# ════════════════════════════════════════════════════════════════════════


class HtmlRendererTests(unittest.TestCase):
    """Test the deterministic HTML renderer."""

    def setUp(self):
        self.doc = FunctionalDocumentation.model_validate(_valid_doc())
        self.html = render_html(self.doc)

    def test_valid_html_structure(self):
        """Output contains required HTML5 structural elements."""
        self.assertIn("<!DOCTYPE html>", self.html)
        self.assertIn("<html", self.html)
        self.assertIn("</html>", self.html)
        self.assertIn("<head>", self.html)
        self.assertIn("</head>", self.html)
        self.assertIn("<body>", self.html)
        self.assertIn("</body>", self.html)

    def test_title_in_head(self):
        """Page <title> contains the workbook title."""
        self.assertIn(
            "<title>Sales Analysis — Functional Documentation</title>",
            self.html,
        )

    def test_inline_css(self):
        """CSS is inline (no external stylesheet links)."""
        self.assertIn("<style>", self.html)
        self.assertNotIn('<link rel="stylesheet"', self.html)

    def test_no_external_js(self):
        """No external JavaScript files are loaded."""
        self.assertNotIn("<script src=", self.html)

    def test_sidebar_toc(self):
        """Sidebar table-of-contents has expected anchor links."""
        self.assertIn('class="toc"', self.html)
        self.assertIn('href="#summary"', self.html)
        self.assertIn('href="#dashboards"', self.html)
        self.assertIn('href="#parameters"', self.html)

    def test_collapsible_details(self):
        """Dashboards and worksheets use <details> elements."""
        self.assertIn("<details", self.html)
        self.assertIn("<summary>", self.html)

    def test_dashboard_section(self):
        """Dashboard section has correct content."""
        self.assertIn('id="dashboards"', self.html)
        self.assertIn("Overview", self.html)

    def test_worksheet_badge(self):
        """Visualization type appears as a badge on worksheets."""
        self.assertIn('class="badge"', self.html)
        self.assertIn("bar", self.html)

    def test_parameters_table(self):
        """Parameters render as an HTML table."""
        self.assertIn('id="parameters"', self.html)
        self.assertIn("<th>Parameter</th>", self.html)
        self.assertIn("Target Quota", self.html)

    def test_html_escaping(self):
        """Special characters in names are HTML-escaped."""
        data = _valid_doc()
        data["workbook_summary"]["title"] = "Sales & <Marketing>"
        doc = FunctionalDocumentation.model_validate(data)
        html = render_html(doc)
        self.assertIn("Sales &amp; &lt;Marketing&gt;", html)
        self.assertNotIn("<Marketing>", html)

    def test_print_media_query(self):
        """Print-friendly CSS is included."""
        self.assertIn("@media print", self.html)

    def test_responsive_media_query(self):
        """Responsive CSS for small screens is included."""
        self.assertIn("@media (max-width: 768px)", self.html)

    def test_minimal_doc_renders(self):
        """A minimal document renders valid HTML."""
        minimal = FunctionalDocumentation.model_validate(
            {
                "workbook_summary": {"title": "Minimal", "purpose": "Test"},
            }
        )
        html = render_html(minimal)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Minimal", html)
        # No dashboards section
        self.assertNotIn('id="dashboards"', html)

    def test_standalone_worksheets_section(self):
        """Standalone worksheets section appears in HTML."""
        self.assertIn('id="standalone-worksheets"', self.html)

    def test_cross_cutting_section(self):
        """Cross-cutting insights section appears in HTML."""
        self.assertIn('id="cross-cutting"', self.html)


# ════════════════════════════════════════════════════════════════════════
#  Agent Init Tests
# ════════════════════════════════════════════════════════════════════════


class AgentInitTests(unittest.TestCase):
    """Test FunctionalDocAgent initialisation (no LLM needed)."""

    def test_skill_name(self):
        """Agent has the correct skill_name."""
        from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent

        agent = FunctionalDocAgent()
        self.assertEqual(agent.skill_name, "tableau_functional_doc_agent")

    def test_custom_settings(self):
        """Agent accepts custom AgentSettings."""
        from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent
        from Tableau2PowerBI.core.config import AgentSettings

        settings = AgentSettings(
            project_endpoint="https://example.com/test",
            max_validation_retries=5,
        )
        agent = FunctionalDocAgent(settings=settings)
        self.assertEqual(agent.settings.max_validation_retries, 5)


class FunctionalDocInputSelectionTests(unittest.TestCase):
    """Tests for full vs slim metadata selection in FunctionalDocAgent."""

    def _agent_settings(self, output_root):
        return AgentSettings(
            project_endpoint="https://example.test",
            output_root=output_root,
            functional_doc_input_threshold_kb=1,
        )

    def _build_agent(self, output_root):
        from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent

        return FunctionalDocAgent(settings=self._agent_settings(output_root))

    def _write_json(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_load_metadata_uses_full_when_under_threshold(self):
        with managed_tempdir() as tmpdir:
            agent = self._build_agent(tmpdir)
            data_dir = tmpdir / "tableau_metadata_extractor_agent" / "SmallBook"
            data_dir.mkdir(parents=True)
            payload = {"dashboards": [], "worksheets": [], "datasources": []}
            self._write_json(data_dir / "tableau_metadata.json", payload)

            loaded = agent._load_metadata("SmallBook", None)

            self.assertEqual(loaded, payload)

    def test_load_metadata_uses_slim_when_full_is_over_threshold(self):
        with managed_tempdir() as tmpdir:
            agent = self._build_agent(tmpdir)
            data_dir = tmpdir / "tableau_metadata_extractor_agent" / "LargeBook"
            data_dir.mkdir(parents=True)
            full_payload = {"padding": "x" * 4096, "dashboards": [], "worksheets": [], "datasources": []}
            slim_payload = {"dashboards": [{"name": "Overview"}], "worksheets": []}
            self._write_json(data_dir / "tableau_metadata.json", full_payload)
            self._write_json(data_dir / "functional_doc_input_slim.json", slim_payload)

            loaded = agent._load_metadata("LargeBook", None)

            self.assertEqual(loaded, slim_payload)

    def test_load_metadata_regenerates_missing_slim(self):
        with managed_tempdir() as tmpdir:
            agent = self._build_agent(tmpdir)
            data_dir = tmpdir / "tableau_metadata_extractor_agent" / "RegenBook"
            data_dir.mkdir(parents=True)
            full_payload = {
                "padding": "x" * 4096,
                "dashboards": [{"name": "Overview", "layout_zones": [{"x": "0"}]}],
                "worksheets": [{"name": "Sheet 1", "cols_shelf": [{"field": "Sales", "raw": "[Sales]"}]}],
                "datasources": [{"name": "Sales", "columns": [{"name": "[Sales]"}], "calculated_fields": []}],
                "parameters": [],
                "actions": [],
            }
            self._write_json(data_dir / "tableau_metadata.json", full_payload)

            loaded = agent._load_metadata("RegenBook", None)

            self.assertTrue((data_dir / "functional_doc_input_slim.json").exists())
            self.assertIn("dashboards", loaded)
            self.assertNotIn("layout_zones", loaded["dashboards"][0])

    def test_load_metadata_warns_when_slim_is_still_large(self):
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
                functional_doc_input_threshold_kb=1,
            )
            from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent

            agent = FunctionalDocAgent(settings=settings)
            data_dir = tmpdir / "tableau_metadata_extractor_agent" / "WarnBook"
            data_dir.mkdir(parents=True)
            full_payload = {"padding": "x" * 4096, "dashboards": [], "worksheets": [], "datasources": []}
            slim_payload = {"padding": "y" * 4096, "dashboards": []}
            self._write_json(data_dir / "tableau_metadata.json", full_payload)
            self._write_json(data_dir / "functional_doc_input_slim.json", slim_payload)

            with self.assertLogs(agent.logger, level=logging.WARNING) as captured:
                loaded = agent._load_metadata("WarnBook", None)

            self.assertEqual(loaded, slim_payload)
            self.assertTrue(any("still large" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()
