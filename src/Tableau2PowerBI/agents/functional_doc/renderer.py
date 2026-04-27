"""Deterministic renderers for functional documentation.

Converts a validated :class:`FunctionalDocumentation` model into two
output formats:

- **Markdown** — portable, version-control friendly, flat text
- **HTML** — self-contained (inline CSS/JS, no external dependencies),
  navigable with collapsible ``<details>`` sections and a sidebar TOC

Both renderers are pure functions: they take a Pydantic model and return
a string.  No I/O, no LLM calls, no side effects.
"""

from __future__ import annotations

import html as html_mod
from textwrap import dedent

from Tableau2PowerBI.agents.functional_doc.models import (
    CrossCuttingInsights,
    DashboardDoc,
    DataSourceDoc,
    FieldDescription,
    FunctionalDocumentation,
    ParameterDoc,
    WorksheetDoc,
)

# ════════════════════════════════════════════════════════════════════════
#  Markdown Renderer
# ════════════════════════════════════════════════════════════════════════


def render_markdown(doc: FunctionalDocumentation) -> str:
    """Render the functional documentation as a Markdown string."""
    lines: list[str] = []

    # ── Workbook summary ───────────────────────────────────────────────
    ws = doc.workbook_summary
    lines.append(f"# {ws.title}\n")
    lines.append(f"{ws.purpose}\n")
    if ws.target_audience:
        lines.append(f"**Target audience:** {ws.target_audience}\n")
    if ws.key_business_questions:
        lines.append("## Key Business Questions\n")
        for q in ws.key_business_questions:
            lines.append(f"- {q}")
        lines.append("")

    # ── Data sources ───────────────────────────────────────────────────
    if doc.data_sources:
        lines.append("## Data Sources\n")
        for ds in doc.data_sources:
            lines.append(f"### {ds.name}\n")
            if ds.purpose:
                lines.append(f"{ds.purpose}\n")
            if ds.key_fields:
                lines.append("| Field | Description |")
                lines.append("|-------|-------------|")
                for f in ds.key_fields:
                    lines.append(f"| {f.name} | {f.description} |")
                lines.append("")
            if ds.relationships_explained:
                lines.append(f"**Relationships:** {ds.relationships_explained}\n")

    # ── Dashboards ─────────────────────────────────────────────────────
    if doc.dashboards:
        lines.append("## Dashboards\n")
        for dash in doc.dashboards:
            lines.append(f"### {dash.name}\n")
            if dash.purpose:
                lines.append(f"{dash.purpose}\n")
            if dash.target_audience:
                lines.append(f"**Target audience:** {dash.target_audience}\n")
            if dash.key_insights:
                lines.append("**Key insights:**\n")
                for insight in dash.key_insights:
                    lines.append(f"- {insight}")
                lines.append("")

            # Worksheets within this dashboard
            for ws_doc in dash.worksheets:
                _render_worksheet_md(ws_doc, lines, heading_level=4)

    # ── Standalone worksheets ──────────────────────────────────────────
    if doc.standalone_worksheets:
        lines.append("## Standalone Worksheets\n")
        for ws_doc in doc.standalone_worksheets:
            _render_worksheet_md(ws_doc, lines, heading_level=3)

    # ── Parameters ─────────────────────────────────────────────────────
    if doc.parameters:
        lines.append("## Parameters\n")
        lines.append("| Parameter | Purpose | Business Impact | Usage |")
        lines.append("|-----------|---------|-----------------|-------|")
        for p in doc.parameters:
            lines.append(f"| {p.name} | {p.purpose} | {p.business_impact} " f"| {p.usage_context} |")
        lines.append("")

    # ── Cross-cutting insights ─────────────────────────────────────────
    cci = doc.cross_cutting_insights
    if cci.data_lineage_summary or cci.interactivity_patterns or cci.limitations_and_notes:
        lines.append("## Cross-Cutting Insights\n")
        if cci.data_lineage_summary:
            lines.append("### Data Lineage\n")
            lines.append(f"{cci.data_lineage_summary}\n")
        if cci.interactivity_patterns:
            lines.append("### Interactivity Patterns\n")
            lines.append(f"{cci.interactivity_patterns}\n")
        if cci.limitations_and_notes:
            lines.append("### Limitations & Notes\n")
            lines.append(f"{cci.limitations_and_notes}\n")

    return "\n".join(lines)


def _render_worksheet_md(
    ws: WorksheetDoc,
    lines: list[str],
    heading_level: int,
) -> None:
    """Append Markdown lines for a single worksheet."""
    prefix = "#" * heading_level
    lines.append(f"{prefix} {ws.name}\n")
    if ws.purpose:
        lines.append(f"{ws.purpose}\n")
    if ws.visualization_type:
        lines.append(f"**Visualization type:** {ws.visualization_type}\n")
    if ws.metrics_shown:
        lines.append(f"**Metrics:** {', '.join(ws.metrics_shown)}\n")
    if ws.dimensions_used:
        lines.append(f"**Dimensions:** {', '.join(ws.dimensions_used)}\n")
    if ws.filters_explained:
        lines.append("**Filters:**\n")
        for flt in ws.filters_explained:
            lines.append(f"- {flt}")
        lines.append("")
    if ws.interactivity:
        lines.append(f"**Interactivity:** {ws.interactivity}\n")
    if ws.calculated_fields_explained:
        lines.append("**Calculated fields:**\n")
        for cf in ws.calculated_fields_explained:
            lines.append(f"- **{cf.name}** — {cf.description}")
        lines.append("")
    if ws.business_interpretation:
        lines.append(f"**Business interpretation:** {ws.business_interpretation}\n")


# ════════════════════════════════════════════════════════════════════════
#  HTML Renderer
# ════════════════════════════════════════════════════════════════════════


def render_html(doc: FunctionalDocumentation) -> str:
    """Render the functional documentation as a self-contained HTML string.

    The output is a complete HTML5 document with inline CSS and JS — no
    external dependencies.  Sections are collapsible via ``<details>``
    elements and a sidebar table-of-contents provides anchor-link
    navigation.
    """
    toc_entries: list[str] = []
    body_sections: list[str] = []

    h = html_mod.escape  # shorthand

    # ── Workbook summary ───────────────────────────────────────────────
    ws = doc.workbook_summary
    body_sections.append(
        f'<header id="summary">'
        f"<h1>{h(ws.title)}</h1>"
        f'<p class="purpose">{h(ws.purpose)}</p>'
        + (
            f'<p class="audience"><strong>Target audience:</strong> ' f"{h(ws.target_audience)}</p>"
            if ws.target_audience
            else ""
        )
        + "</header>"
    )
    toc_entries.append('<a href="#summary">Summary</a>')

    if ws.key_business_questions:
        items = "".join(f"<li>{h(q)}</li>" for q in ws.key_business_questions)
        body_sections.append(
            f'<section id="business-questions">' f"<h2>Key Business Questions</h2><ul>{items}</ul></section>"
        )
        toc_entries.append('<a href="#business-questions">Key Business Questions</a>')

    # ── Data sources ───────────────────────────────────────────────────
    if doc.data_sources:
        ds_html = _render_data_sources_html(doc.data_sources, h)
        body_sections.append(ds_html)
        toc_entries.append('<a href="#data-sources">Data Sources</a>')

    # ── Dashboards ─────────────────────────────────────────────────────
    if doc.dashboards:
        dash_html, dash_toc = _render_dashboards_html(doc.dashboards, h)
        body_sections.append(dash_html)
        toc_entries.append('<a href="#dashboards">Dashboards</a>')
        toc_entries.extend(dash_toc)

    # ── Standalone worksheets ──────────────────────────────────────────
    if doc.standalone_worksheets:
        sw_html = _render_standalone_worksheets_html(
            doc.standalone_worksheets,
            h,
        )
        body_sections.append(sw_html)
        toc_entries.append('<a href="#standalone-worksheets">Standalone Worksheets</a>')

    # ── Parameters ─────────────────────────────────────────────────────
    if doc.parameters:
        param_html = _render_parameters_html(doc.parameters, h)
        body_sections.append(param_html)
        toc_entries.append('<a href="#parameters">Parameters</a>')

    # ── Cross-cutting insights ─────────────────────────────────────────
    cci = doc.cross_cutting_insights
    if cci.data_lineage_summary or cci.interactivity_patterns or cci.limitations_and_notes:
        cci_html = _render_cross_cutting_html(cci, h)
        body_sections.append(cci_html)
        toc_entries.append('<a href="#cross-cutting">Cross-Cutting Insights</a>')

    # ── Assemble full page ─────────────────────────────────────────────
    toc_items = "".join(f"<li>{e}</li>" for e in toc_entries)
    body = "\n".join(body_sections)

    return _HTML_TEMPLATE.format(
        title=h(ws.title),
        toc_items=toc_items,
        body=body,
    )


# ── HTML section helpers ───────────────────────────────────────────────


def _render_data_sources_html(
    sources: list[DataSourceDoc],
    h,
) -> str:
    """Build the Data Sources HTML section."""
    parts: list[str] = ['<section id="data-sources"><h2>Data Sources</h2>']
    for ds in sources:
        slug = _slug(ds.name)
        inner = f"<p>{h(ds.purpose)}</p>" if ds.purpose else ""
        if ds.key_fields:
            inner += _fields_table_html(ds.key_fields, h)
        if ds.relationships_explained:
            inner += f"<p><strong>Relationships:</strong> " f"{h(ds.relationships_explained)}</p>"
        parts.append(f'<details open id="ds-{slug}">' f"<summary>{h(ds.name)}</summary>{inner}</details>")
    parts.append("</section>")
    return "\n".join(parts)


def _render_dashboards_html(
    dashboards: list[DashboardDoc],
    h,
) -> tuple[str, list[str]]:
    """Build the Dashboards HTML section and sub-TOC entries."""
    parts: list[str] = ['<section id="dashboards"><h2>Dashboards</h2>']
    toc_sub: list[str] = []

    for dash in dashboards:
        slug = _slug(dash.name)
        toc_sub.append(f'<li class="toc-sub"><a href="#dash-{slug}">{h(dash.name)}</a></li>')
        inner = ""
        if dash.purpose:
            inner += f"<p>{h(dash.purpose)}</p>"
        if dash.target_audience:
            inner += f"<p><strong>Target audience:</strong> " f"{h(dash.target_audience)}</p>"
        if dash.key_insights:
            items = "".join(f"<li>{h(i)}</li>" for i in dash.key_insights)
            inner += f"<p><strong>Key insights:</strong></p><ul>{items}</ul>"

        # Nested worksheets
        for ws in dash.worksheets:
            inner += _render_worksheet_html(ws, h)

        parts.append(f'<details open id="dash-{slug}">' f"<summary>{h(dash.name)}</summary>{inner}</details>")

    parts.append("</section>")
    return "\n".join(parts), toc_sub


def _render_standalone_worksheets_html(
    worksheets: list[WorksheetDoc],
    h,
) -> str:
    """Build the Standalone Worksheets HTML section."""
    parts: list[str] = ['<section id="standalone-worksheets">' "<h2>Standalone Worksheets</h2>"]
    for ws in worksheets:
        parts.append(_render_worksheet_html(ws, h))
    parts.append("</section>")
    return "\n".join(parts)


def _render_worksheet_html(ws: WorksheetDoc, h) -> str:
    """Render a single worksheet as a collapsible ``<details>`` block."""
    slug = _slug(ws.name)
    badge = f' <span class="badge">{h(ws.visualization_type)}</span>' if ws.visualization_type else ""
    inner = ""
    if ws.purpose:
        inner += f"<p>{h(ws.purpose)}</p>"
    if ws.metrics_shown:
        inner += f"<p><strong>Metrics:</strong> " f"{h(', '.join(ws.metrics_shown))}</p>"
    if ws.dimensions_used:
        inner += f"<p><strong>Dimensions:</strong> " f"{h(', '.join(ws.dimensions_used))}</p>"
    if ws.filters_explained:
        items = "".join(f"<li>{h(f)}</li>" for f in ws.filters_explained)
        inner += f"<p><strong>Filters:</strong></p><ul>{items}</ul>"
    if ws.interactivity:
        inner += f"<p><strong>Interactivity:</strong> " f"{h(ws.interactivity)}</p>"
    if ws.calculated_fields_explained:
        inner += _fields_table_html(
            ws.calculated_fields_explained,
            h,
            header=("Calculated Field", "Business Logic"),
        )
    if ws.business_interpretation:
        inner += f"<p><strong>Business interpretation:</strong> " f"{h(ws.business_interpretation)}</p>"
    return f'<details class="worksheet" id="ws-{slug}">' f"<summary>{h(ws.name)}{badge}</summary>{inner}</details>"


def _render_parameters_html(
    parameters: list[ParameterDoc],
    h,
) -> str:
    """Build the Parameters HTML section as a table."""
    rows = "".join(
        f"<tr><td>{h(p.name)}</td><td>{h(p.purpose)}</td>"
        f"<td>{h(p.business_impact)}</td><td>{h(p.usage_context)}</td></tr>"
        for p in parameters
    )
    return (
        '<section id="parameters"><h2>Parameters</h2>'
        "<table><thead><tr>"
        "<th>Parameter</th><th>Purpose</th>"
        "<th>Business Impact</th><th>Usage</th>"
        "</tr></thead><tbody>"
        f"{rows}</tbody></table></section>"
    )


def _render_cross_cutting_html(
    cci: CrossCuttingInsights,
    h,
) -> str:
    """Build the Cross-Cutting Insights HTML section."""
    parts: list[str] = ['<section id="cross-cutting">' "<h2>Cross-Cutting Insights</h2>"]
    if cci.data_lineage_summary:
        parts.append(f"<h3>Data Lineage</h3><p>{h(cci.data_lineage_summary)}</p>")
    if cci.interactivity_patterns:
        parts.append(f"<h3>Interactivity Patterns</h3>" f"<p>{h(cci.interactivity_patterns)}</p>")
    if cci.limitations_and_notes:
        parts.append(f"<h3>Limitations &amp; Notes</h3>" f"<p>{h(cci.limitations_and_notes)}</p>")
    parts.append("</section>")
    return "\n".join(parts)


# ── Shared helpers ─────────────────────────────────────────────────────


def _fields_table_html(
    fields: list[FieldDescription],
    h,
    header: tuple[str, str] = ("Field", "Description"),
) -> str:
    """Render a list of fields as an HTML table."""
    rows = "".join(f"<tr><td>{h(f.name)}</td><td>{h(f.description)}</td></tr>" for f in fields)
    return f"<table><thead><tr><th>{header[0]}</th><th>{header[1]}</th>" f"</tr></thead><tbody>{rows}</tbody></table>"


def _slug(text: str) -> str:
    """Convert a display name to a URL-safe anchor slug."""
    import re

    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")


# ── HTML template (self-contained) ─────────────────────────────────────

_HTML_TEMPLATE = dedent("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Functional Documentation</title>
<style>
:root {{
  --bg: #f8f9fa;
  --card-bg: #ffffff;
  --border: #dee2e6;
  --primary: #4361ee;
  --primary-light: #eef0ff;
  --text: #212529;
  --text-muted: #6c757d;
  --accent: #7209b7;
}}
*, *::before, *::after {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  color: var(--text);
  background: var(--bg);
  display: flex;
  min-height: 100vh;
}}
/* ── Sidebar TOC ── */
nav.toc {{
  position: sticky;
  top: 0;
  width: 260px;
  min-width: 220px;
  height: 100vh;
  overflow-y: auto;
  padding: 1.5rem 1rem;
  background: var(--card-bg);
  border-right: 1px solid var(--border);
  flex-shrink: 0;
}}
nav.toc h2 {{ font-size: 0.85rem; text-transform: uppercase;
              letter-spacing: 0.05em; color: var(--text-muted); margin-top: 0; }}
nav.toc ul {{ list-style: none; padding: 0; margin: 0; }}
nav.toc li {{ margin: 0.3rem 0; }}
nav.toc li.toc-sub {{ padding-left: 1rem; font-size: 0.9rem; }}
nav.toc a {{ text-decoration: none; color: var(--primary);
             transition: color 0.15s; }}
nav.toc a:hover {{ color: var(--accent); }}
/* ── Main content ── */
main {{
  flex: 1;
  max-width: 960px;
  margin: 0 auto;
  padding: 2rem 2.5rem;
}}
header {{ margin-bottom: 2rem; }}
header h1 {{ margin: 0 0 0.5rem; }}
.purpose {{ font-size: 1.1rem; color: var(--text-muted); }}
.audience {{ font-size: 0.95rem; }}
section {{ margin-bottom: 2.5rem; }}
h2 {{ border-bottom: 2px solid var(--primary); padding-bottom: 0.3rem; }}
details {{
  margin: 0.5rem 0;
  padding: 0.75rem 1rem;
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 6px;
}}
details.worksheet {{
  margin-left: 1rem;
  border-left: 3px solid var(--primary-light);
}}
summary {{
  cursor: pointer;
  font-weight: 600;
  font-size: 1.05rem;
  user-select: none;
}}
summary:hover {{ color: var(--primary); }}
.badge {{
  display: inline-block;
  font-size: 0.75rem;
  font-weight: 500;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  background: var(--primary-light);
  color: var(--primary);
  margin-left: 0.4rem;
  vertical-align: middle;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  margin: 0.75rem 0;
  font-size: 0.92rem;
}}
th, td {{
  text-align: left;
  padding: 0.45rem 0.6rem;
  border-bottom: 1px solid var(--border);
}}
th {{ background: var(--primary-light); font-weight: 600; }}
/* ── Print ── */
@media print {{
  nav.toc {{ display: none; }}
  body {{ display: block; }}
  main {{ max-width: 100%; padding: 1rem; }}
  details {{ border: none; padding: 0; }}
  details[open] > summary {{ font-size: 1rem; }}
}}
/* ── Responsive: collapse sidebar on small screens ── */
@media (max-width: 768px) {{
  nav.toc {{ display: none; }}
  body {{ display: block; }}
  main {{ padding: 1rem; }}
}}
</style>
</head>
<body>
<nav class="toc">
<h2>Contents</h2>
<ul>
{toc_items}
</ul>
</nav>
<main>
{body}
</main>
</body>
</html>
""")
