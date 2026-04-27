"""Input loading and prompt/schema helpers for PBIR report generation."""

from __future__ import annotations

import json
import logging

from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.output_dirs import get_output_dir


def load_tdd_sections(workbook_name: str, settings: AgentSettings, logger: logging.Logger) -> tuple[dict, dict, dict]:
    """Load TDD report, semantic model, and DAX design sections."""
    tdd_dir = get_output_dir("target_technical_doc_agent", workbook_name, settings)
    report_path = tdd_dir / "report_design.json"
    sm_path = tdd_dir / "semantic_model_design.json"
    dax_path = tdd_dir / "dax_measures_design.json"

    if not report_path.exists():
        raise FileNotFoundError(
            f"TDD report design not found: {report_path}. Run the target technical doc agent first."
        )
    if not sm_path.exists():
        raise FileNotFoundError(
            f"TDD semantic model design not found: {sm_path}. Run the target technical doc agent first."
        )

    logger.info("Loading TDD from %s", tdd_dir.name)
    tdd_report = json.loads(report_path.read_text(encoding="utf-8"))
    tdd_sm = json.loads(sm_path.read_text(encoding="utf-8"))
    tdd_dax: dict = {}
    if dax_path.exists():
        tdd_dax = json.loads(dax_path.read_text(encoding="utf-8"))

    return tdd_report, tdd_sm, tdd_dax


def build_schema_from_tdd_sections(tdd_sm: dict, tdd_dax: dict, tdd_report: dict) -> str:
    """Build a compact schema summary from TDD design sections."""
    table_columns: dict[str, list[str]] = {}
    for table in tdd_sm.get("tables", []):
        table_name = table.get("name", "")
        columns = [c.get("name", "") for c in table.get("columns", [])]
        table_columns[table_name] = columns

    table_measures: dict[str, list[str]] = {}
    for measure in tdd_dax.get("measures", []):
        owner = measure.get("owner_table", "")
        caption = measure.get("caption", "")
        if owner and caption:
            table_measures.setdefault(owner, []).append(caption)

    lines: list[str] = [
        "Power BI table and column names (use EXACTLY these names for all "
        "Entity and queryRef references — do NOT use Tableau datasource names):"
    ]
    for table_name, columns in table_columns.items():
        col_summary = ", ".join(columns) if columns else "(no columns)"
        measures = table_measures.get(table_name, [])
        measure_summary = ", ".join(measures) if measures else "(no measures)"
        lines.append(f"  - {table_name}:")
        lines.append(f"      Columns: {col_summary}")
        lines.append(f"      Measures: {measure_summary}")

    for table_name, measures in table_measures.items():
        if table_name not in table_columns:
            measure_summary = ", ".join(measures)
            lines.append(f"  - {table_name}:")
            lines.append("      Columns: (no columns)")
            lines.append(f"      Measures: {measure_summary}")

    entity_resolution = tdd_report.get("entity_resolution", {})
    calc_mapping = entity_resolution.get("calculated_field_map", {})
    if calc_mapping:
        lines.append("")
        lines.append(
            "Tableau calculated field → Power BI measure name mapping "
            "(use the PBI name, NOT the Calculation_XXX name):"
        )
        for calc_name, pbi_name in sorted(calc_mapping.items()):
            lines.append(f"  - {calc_name} → {pbi_name}")

    return "\n".join(lines)
