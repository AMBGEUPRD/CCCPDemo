"""Deterministic renderers for the Target Technical Documentation.

Converts a validated :class:`TargetTechnicalDocumentation` model into
two output formats:

- **Markdown** — portable, version-control friendly, flat text
- **HTML** — self-contained (inline CSS/JS, no external dependencies),
  navigable with collapsible ``<details>`` sections and a sidebar TOC

Both renderers are pure functions: they take a Pydantic model and return
a string.  No I/O, no LLM calls, no side effects.
"""

from __future__ import annotations

import html as html_mod
import re
from textwrap import dedent

from Tableau2PowerBI.agents.target_technical_doc.models import (
    DaxMeasuresDesign,
    MigrationAssessment,
    ReportDesign,
    SemanticModelDesign,
    TargetTechnicalDocumentation,
)

# ════════════════════════════════════════════════════════════════════════
#  Markdown Renderer
# ════════════════════════════════════════════════════════════════════════


def render_markdown(doc: TargetTechnicalDocumentation) -> str:
    """Render the TDD as a Markdown string."""
    lines: list[str] = []

    lines.append("# Target Technical Documentation\n")

    # ── Migration Assessment ───────────────────────────────────────────
    _render_assessment_md(doc.assessment, lines)

    # ── Semantic Model Design ──────────────────────────────────────────
    _render_semantic_model_md(doc.semantic_model, lines)

    # ── DAX Measures Design ────────────────────────────────────────────
    _render_dax_measures_md(doc.dax_measures, lines)

    # ── Report Design ──────────────────────────────────────────────────
    _render_report_md(doc.report, lines)

    return "\n".join(lines)


def _render_assessment_md(
    assessment: MigrationAssessment,
    lines: list[str],
) -> None:
    """Append Markdown for the migration assessment section."""
    lines.append("## Migration Assessment\n")
    lines.append(f"**Complexity:** {assessment.complexity_score}\n")
    if assessment.summary:
        lines.append(f"{assessment.summary}\n")

    if assessment.warnings:
        lines.append("### Warnings\n")
        lines.append("| Code | Severity | Message | Recommendation |")
        lines.append("|------|----------|---------|----------------|")
        for w in assessment.warnings:
            lines.append(f"| `{w.code}` | {w.severity} | {w.message} " f"| {w.recommendation} |")
        lines.append("")

    if assessment.manual_items:
        lines.append("### Manual Review Items\n")
        for item in assessment.manual_items:
            lines.append(f"- {item}")
        lines.append("")


def _render_semantic_model_md(
    sm: SemanticModelDesign,
    lines: list[str],
) -> None:
    """Append Markdown for the semantic model design section."""
    lines.append("## Semantic Model Design\n")
    lines.append(f"**Locale:** `{sm.source_query_culture}`\n")

    # Tables
    lines.append("### Tables\n")
    for table in sm.tables:
        lines.append(f"#### {table.name}\n")
        if table.description:
            lines.append(f"{table.description}\n")
        lines.append(f"- **Source:** {table.source_datasource} → {table.source_table}")
        lines.append(f"- **Query group:** {table.query_group}")
        strat = table.m_query_strategy
        lines.append(f"- **Connector:** `{strat.connector_type}`")
        if strat.notes:
            lines.append(f"- **Notes:** {strat.notes}")
        lines.append("")

        if table.columns:
            lines.append("| Column | Source | Type | Summarize | Description |")
            lines.append("|--------|--------|------|-----------|-------------|")
            for col in table.columns:
                lines.append(
                    f"| {col.name} | {col.source_column} "
                    f"| `{col.data_type}` | {col.summarize_by} "
                    f"| {col.description} |"
                )
            lines.append("")

    # Relationships
    if sm.relationships:
        lines.append("### Relationships\n")
        lines.append("| From | → | To | Cardinality | Direction | Confidence |")
        lines.append("|------|---|-----|-------------|-----------|------------|")
        for rel in sm.relationships:
            lines.append(
                f"| {rel.from_table}.{rel.from_column} | → "
                f"| {rel.to_table}.{rel.to_column} "
                f"| {rel.cardinality} | {rel.cross_filter_direction} "
                f"| {rel.confidence} |"
            )
        lines.append("")

    # Parameters
    if sm.parameters:
        lines.append("### Parameters\n")
        lines.append("| Name | Type | Default | Description |")
        lines.append("|------|------|---------|-------------|")
        for p in sm.parameters:
            lines.append(f"| {p.name} | `{p.pbi_type}` | `{p.default_value}` " f"| {p.description} |")
        lines.append("")


def _render_dax_measures_md(
    dax: DaxMeasuresDesign,
    lines: list[str],
) -> None:
    """Append Markdown for the DAX measures design section."""
    lines.append("## DAX Measures Design\n")

    if dax.measures:
        # Group by translatability
        direct = [m for m in dax.measures if m.translatability == "direct"]
        redesign = [m for m in dax.measures if m.translatability == "redesign"]
        manual = [m for m in dax.measures if m.translatability == "manual"]

        if direct:
            lines.append(f"### Direct Translation ({len(direct)} measures)\n")
            lines.append("| Measure | Table | Approach |")
            lines.append("|---------|-------|----------|")
            for m in direct:
                lines.append(f"| {m.caption} | {m.owner_table} " f"| {m.target_dax_approach} |")
            lines.append("")

        if redesign:
            lines.append(f"### Redesign Required ({len(redesign)} measures)\n")
            lines.append("| Measure | Table | Approach | Notes |")
            lines.append("|---------|-------|----------|-------|")
            for m in redesign:
                lines.append(f"| {m.caption} | {m.owner_table} " f"| {m.target_dax_approach} | {m.notes} |")
            lines.append("")

        if manual:
            lines.append(f"### Manual Translation ({len(manual)} measures)\n")
            lines.append("| Measure | Table | Notes |")
            lines.append("|---------|-------|-------|")
            for m in manual:
                lines.append(f"| {m.caption} | {m.owner_table} | {m.notes} |")
            lines.append("")

    if dax.untranslatable:
        lines.append("### Untranslatable Items\n")
        lines.append("| Item | Reason | Suggestion |")
        lines.append("|------|--------|------------|")
        for u in dax.untranslatable:
            lines.append(f"| {u.caption} | {u.reason} | {u.suggestion} |")
        lines.append("")


def _render_report_md(
    report: ReportDesign,
    lines: list[str],
) -> None:
    """Append Markdown for the report design section."""
    lines.append("## Report Design\n")

    for page in report.pages:
        lines.append(f"### Page: {page.display_name}\n")
        lines.append(f"- **Source dashboard:** {page.dashboard_name}")
        lines.append(f"- **Dimensions:** {page.width}×{page.height}")
        lines.append(f"- **Visuals:** {len(page.visuals)}")
        lines.append("")

        for vis in page.visuals:
            lines.append(f"#### {vis.worksheet_name} (`{vis.visual_type}`)\n")
            if vis.title:
                lines.append(f"**Title:** {vis.title}\n")
            if vis.position:
                pos = vis.position
                lines.append(
                    f"**Position:** x={pos.get('x', 0)}, "
                    f"y={pos.get('y', 0)}, "
                    f"w={pos.get('width', 0)}, "
                    f"h={pos.get('height', 0)}\n"
                )
            if vis.field_bindings:
                lines.append("| Tableau Field | PBI Table | PBI Field | Kind | Agg |")
                lines.append("|---------------|-----------|-----------|------|-----|")
                for fb in vis.field_bindings:
                    lines.append(
                        f"| {fb.tableau_field} | {fb.pbi_table} "
                        f"| {fb.pbi_field} | {fb.field_kind} "
                        f"| {fb.aggregation} |"
                    )
                lines.append("")
            if vis.filters:
                lines.append("**Filters:** " + ", ".join(vis.filters) + "\n")

    if report.standalone_worksheets:
        lines.append("### Standalone Worksheets\n")
        for ws_name in report.standalone_worksheets:
            lines.append(f"- {ws_name}")
        lines.append("")

    if report.entity_resolution.datasource_to_table:
        lines.append("### Entity Resolution Map\n")
        lines.append("| Tableau Datasource ID | PBI Table |")
        lines.append("|-----------------------|-----------|")
        for ds_id, tbl in report.entity_resolution.datasource_to_table.items():
            lines.append(f"| `{ds_id}` | {tbl} |")
        lines.append("")


# ════════════════════════════════════════════════════════════════════════
#  HTML Renderer
# ════════════════════════════════════════════════════════════════════════


def render_html(doc: TargetTechnicalDocumentation) -> str:
    """Render the TDD as a self-contained HTML string.

    Output is a complete HTML5 document with inline CSS — no external
    dependencies.  Sections are collapsible via ``<details>`` elements
    and a sidebar TOC provides anchor-link navigation.
    """
    h = html_mod.escape
    toc_entries: list[str] = []
    body_sections: list[str] = []

    # ── Header ─────────────────────────────────────────────────────────
    body_sections.append('<header id="top">' "<h1>Target Technical Documentation</h1>" "</header>")

    # ── Assessment ─────────────────────────────────────────────────────
    body_sections.append(_render_assessment_html(doc.assessment, h))
    toc_entries.append('<a href="#assessment">Migration Assessment</a>')

    # ── Semantic Model ─────────────────────────────────────────────────
    body_sections.append(_render_semantic_model_html(doc.semantic_model, h))
    toc_entries.append('<a href="#semantic-model">Semantic Model</a>')
    for table in doc.semantic_model.tables:
        slug = _slug(table.name)
        toc_entries.append(f'<li class="toc-sub"><a href="#tbl-{slug}">' f"{h(table.name)}</a></li>")

    # ── DAX Measures ───────────────────────────────────────────────────
    body_sections.append(_render_dax_measures_html(doc.dax_measures, h))
    toc_entries.append('<a href="#dax-measures">DAX Measures</a>')

    # ── Report Design ──────────────────────────────────────────────────
    body_sections.append(_render_report_html(doc.report, h))
    toc_entries.append('<a href="#report">Report Design</a>')
    for page in doc.report.pages:
        slug = _slug(page.display_name or page.dashboard_name)
        toc_entries.append(f'<li class="toc-sub"><a href="#page-{slug}">' f"{h(page.display_name)}</a></li>")

    # ── Assemble ───────────────────────────────────────────────────────
    toc_items = "".join(f"<li>{e}</li>" for e in toc_entries)
    body = "\n".join(body_sections)
    return _HTML_TEMPLATE.format(title="Target Technical Documentation", toc_items=toc_items, body=body)


# ── HTML section helpers ───────────────────────────────────────────────


def _render_assessment_html(
    assessment: MigrationAssessment,
    h,
) -> str:
    """Build the Migration Assessment HTML section."""
    parts: list[str] = [
        '<section id="assessment">'
        "<h2>Migration Assessment</h2>"
        f"<p><strong>Complexity:</strong> "
        f'<span class="badge">{h(assessment.complexity_score)}</span></p>'
    ]
    if assessment.summary:
        parts.append(f"<p>{h(assessment.summary)}</p>")

    if assessment.warnings:
        rows = "".join(
            f"<tr><td><code>{h(w.code)}</code></td>"
            f"<td>{h(w.severity)}</td>"
            f"<td>{h(w.message)}</td>"
            f"<td>{h(w.recommendation)}</td></tr>"
            for w in assessment.warnings
        )
        parts.append(
            "<h3>Warnings</h3>"
            "<table><thead><tr>"
            "<th>Code</th><th>Severity</th><th>Message</th>"
            "<th>Recommendation</th>"
            "</tr></thead><tbody>"
            f"{rows}</tbody></table>"
        )

    if assessment.manual_items:
        items = "".join(f"<li>{h(i)}</li>" for i in assessment.manual_items)
        parts.append(f"<h3>Manual Review Items</h3><ul>{items}</ul>")

    parts.append("</section>")
    return "\n".join(parts)


def _render_semantic_model_html(
    sm: SemanticModelDesign,
    h,
) -> str:
    """Build the Semantic Model Design HTML section."""
    parts: list[str] = [
        '<section id="semantic-model">'
        "<h2>Semantic Model Design</h2>"
        f"<p><strong>Locale:</strong> <code>{h(sm.source_query_culture)}</code></p>"
    ]

    for table in sm.tables:
        slug = _slug(table.name)
        inner = ""
        if table.description:
            inner += f"<p>{h(table.description)}</p>"
        inner += (
            f"<p><strong>Source:</strong> {h(table.source_datasource)} "
            f"→ {h(table.source_table)}</p>"
            f"<p><strong>Query group:</strong> {h(table.query_group)}</p>"
            f"<p><strong>Connector:</strong> "
            f"<code>{h(table.m_query_strategy.connector_type)}</code></p>"
        )
        if table.m_query_strategy.notes:
            inner += f"<p><strong>Notes:</strong> " f"{h(table.m_query_strategy.notes)}</p>"

        if table.columns:
            col_rows = "".join(
                f"<tr><td>{h(c.name)}</td>"
                f"<td>{h(c.source_column)}</td>"
                f"<td><code>{h(c.data_type)}</code></td>"
                f"<td>{h(c.summarize_by)}</td>"
                f"<td>{h(c.description)}</td></tr>"
                for c in table.columns
            )
            inner += (
                "<table><thead><tr>"
                "<th>Column</th><th>Source</th><th>Type</th>"
                "<th>Summarize</th><th>Description</th>"
                f"</tr></thead><tbody>{col_rows}</tbody></table>"
            )

        parts.append(
            f'<details open id="tbl-{slug}">'
            f"<summary>{h(table.name)} "
            f'<span class="badge">{h(table.query_group)}</span>'
            f"</summary>{inner}</details>"
        )

    # Relationships
    if sm.relationships:
        rel_rows = "".join(
            f"<tr><td>{h(r.from_table)}.{h(r.from_column)}</td>"
            f"<td>{h(r.to_table)}.{h(r.to_column)}</td>"
            f"<td>{h(r.cardinality)}</td>"
            f"<td>{h(r.cross_filter_direction)}</td>"
            f"<td>{h(r.confidence)}</td></tr>"
            for r in sm.relationships
        )
        parts.append(
            "<h3>Relationships</h3>"
            "<table><thead><tr>"
            "<th>From</th><th>To</th><th>Cardinality</th>"
            "<th>Direction</th><th>Confidence</th>"
            f"</tr></thead><tbody>{rel_rows}</tbody></table>"
        )

    # Parameters
    if sm.parameters:
        param_rows = "".join(
            f"<tr><td>{h(p.name)}</td>"
            f"<td><code>{h(p.pbi_type)}</code></td>"
            f"<td><code>{h(p.default_value)}</code></td>"
            f"<td>{h(p.description)}</td></tr>"
            for p in sm.parameters
        )
        parts.append(
            "<h3>Parameters</h3>"
            "<table><thead><tr>"
            "<th>Name</th><th>Type</th><th>Default</th>"
            "<th>Description</th>"
            f"</tr></thead><tbody>{param_rows}</tbody></table>"
        )

    parts.append("</section>")
    return "\n".join(parts)


def _render_dax_measures_html(
    dax: DaxMeasuresDesign,
    h,
) -> str:
    """Build the DAX Measures Design HTML section."""
    parts: list[str] = ['<section id="dax-measures">' "<h2>DAX Measures Design</h2>"]

    direct = [m for m in dax.measures if m.translatability == "direct"]
    redesign = [m for m in dax.measures if m.translatability == "redesign"]
    manual = [m for m in dax.measures if m.translatability == "manual"]

    for label, measures in [
        ("Direct Translation", direct),
        ("Redesign Required", redesign),
        ("Manual Translation", manual),
    ]:
        if not measures:
            continue
        rows = "".join(
            f"<tr><td>{h(m.caption)}</td>"
            f"<td>{h(m.owner_table)}</td>"
            f"<td>{h(m.target_dax_approach)}</td>"
            f"<td>{h(m.notes)}</td></tr>"
            for m in measures
        )
        parts.append(
            f"<h3>{label} ({len(measures)})</h3>"
            "<table><thead><tr>"
            "<th>Measure</th><th>Table</th><th>Approach</th><th>Notes</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )

    if dax.untranslatable:
        rows = "".join(
            f"<tr><td>{h(u.caption)}</td>" f"<td>{h(u.reason)}</td>" f"<td>{h(u.suggestion)}</td></tr>"
            for u in dax.untranslatable
        )
        parts.append(
            "<h3>Untranslatable Items</h3>"
            "<table><thead><tr>"
            "<th>Item</th><th>Reason</th><th>Suggestion</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )

    parts.append("</section>")
    return "\n".join(parts)


def _render_report_html(
    report: ReportDesign,
    h,
) -> str:
    """Build the Report Design HTML section."""
    parts: list[str] = ['<section id="report">' "<h2>Report Design</h2>"]

    for page in report.pages:
        slug = _slug(page.display_name or page.dashboard_name)
        inner = (
            f"<p><strong>Source dashboard:</strong> {h(page.dashboard_name)}</p>"
            f"<p><strong>Dimensions:</strong> {page.width}×{page.height}</p>"
        )

        for vis in page.visuals:
            vis_inner = ""
            if vis.title:
                vis_inner += f"<p><strong>Title:</strong> {h(vis.title)}</p>"
            if vis.position:
                pos = vis.position
                vis_inner += (
                    f"<p><strong>Position:</strong> "
                    f"x={pos.get('x', 0)}, y={pos.get('y', 0)}, "
                    f"w={pos.get('width', 0)}, h={pos.get('height', 0)}</p>"
                )
            if vis.field_bindings:
                fb_rows = "".join(
                    f"<tr><td>{h(fb.tableau_field)}</td>"
                    f"<td>{h(fb.pbi_table)}</td>"
                    f"<td>{h(fb.pbi_field)}</td>"
                    f"<td>{h(fb.field_kind)}</td>"
                    f"<td>{h(fb.aggregation)}</td></tr>"
                    for fb in vis.field_bindings
                )
                vis_inner += (
                    "<table><thead><tr>"
                    "<th>Tableau Field</th><th>PBI Table</th>"
                    "<th>PBI Field</th><th>Kind</th><th>Agg</th>"
                    f"</tr></thead><tbody>{fb_rows}</tbody></table>"
                )
            if vis.filters:
                vis_inner += "<p><strong>Filters:</strong> " f"{h(', '.join(vis.filters))}</p>"
            inner += (
                f'<details class="visual">'
                f"<summary>{h(vis.worksheet_name)} "
                f'<span class="badge">{h(vis.visual_type)}</span>'
                f"</summary>{vis_inner}</details>"
            )

        parts.append(
            f'<details open id="page-{slug}">' f"<summary>{h(page.display_name)}</summary>" f"{inner}</details>"
        )

    if report.standalone_worksheets:
        items = "".join(f"<li>{h(ws)}</li>" for ws in report.standalone_worksheets)
        parts.append("<h3>Standalone Worksheets</h3>" f"<ul>{items}</ul>")

    parts.append("</section>")
    return "\n".join(parts)


# ── Shared helpers ─────────────────────────────────────────────────────


def _slug(text: str) -> str:
    """Convert a display name to a URL-safe anchor slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")


# ── HTML template ──────────────────────────────────────────────────────

_HTML_TEMPLATE = dedent("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg: #f8f9fa; --card-bg: #fff; --border: #dee2e6;
  --primary: #4361ee; --text: #212529; --text-muted: #6c757d;
  --accent: #7209b7;
}}
*, *::before, *::after {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  color: var(--text); background: var(--bg);
  display: flex; min-height: 100vh;
}}
nav.toc {{
  position: sticky; top: 0; width: 260px; min-width: 220px;
  height: 100vh; overflow-y: auto; padding: 1.5rem 1rem;
  background: var(--card-bg); border-right: 1px solid var(--border);
  flex-shrink: 0;
}}
nav.toc h2 {{ font-size: .85rem; text-transform: uppercase;
              letter-spacing: .05em; color: var(--text-muted); margin-top: 0; }}
nav.toc ul {{ list-style: none; padding: 0; margin: 0; }}
nav.toc li {{ margin: .3rem 0; }}
nav.toc li.toc-sub {{ padding-left: 1rem; font-size: .9rem; }}
nav.toc a {{ text-decoration: none; color: var(--primary); }}
nav.toc a:hover {{ color: var(--accent); }}
main {{
  flex: 1; max-width: 960px; margin: 0 auto;
  padding: 2rem 2.5rem;
}}
h1 {{ margin-top: 0; }}
h2 {{ border-bottom: 2px solid var(--primary); padding-bottom: .3rem; }}
details {{ margin: .8rem 0; border: 1px solid var(--border);
           border-radius: 6px; background: var(--card-bg); }}
details > summary {{
  cursor: pointer; padding: .6rem 1rem; font-weight: 600;
}}
details > summary:hover {{ background: #eef0ff; }}
details[open] > summary {{ border-bottom: 1px solid var(--border); }}
details .visual {{ margin: .5rem 1rem; }}
table {{ width: 100%; border-collapse: collapse; margin: .8rem 0;
         font-size: .9rem; }}
th, td {{ border: 1px solid var(--border); padding: .4rem .6rem;
          text-align: left; }}
th {{ background: #f1f3f5; font-weight: 600; }}
.badge {{
  display: inline-block; padding: .15rem .5rem; border-radius: 4px;
  font-size: .75rem; font-weight: 600;
  background: var(--primary); color: #fff;
}}
code {{ background: #f1f3f5; padding: .1rem .3rem; border-radius: 3px;
        font-size: .85em; }}
</style>
</head>
<body>
<nav class="toc">
  <h2>Contents</h2>
  <ul>{toc_items}</ul>
</nav>
<main>
{body}
</main>
</body>
</html>
""")
