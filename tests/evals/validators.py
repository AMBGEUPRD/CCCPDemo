"""Structural validators for LLM agent outputs.

Pure functions that check structural invariants on agent outputs.
Used by eval tests to assess LLM quality independently of Pydantic
schema validation (which the agents already perform internally).

These validators return a list of failure messages — an empty list
means all checks passed.
"""

from __future__ import annotations

import json

from Tableau2PowerBI.agents.semantic_model.models import SemanticModelDecisions

# ═══════════════════════════════════════════════════════════════════════════
#  Semantic Model (Stage 3)
# ═══════════════════════════════════════════════════════════════════════════


def validate_semantic_model_structure(
    decisions: SemanticModelDecisions,
    input_metadata: dict,
) -> list[str]:
    """Check structural invariants on semantic model decisions.

    Args:
        decisions: The validated Pydantic model from the LLM.
        input_metadata: The ``semantic_model_input.json`` that was sent
            to the LLM.

    Returns:
        A list of failure descriptions.  Empty means all checks passed.
    """
    failures: list[str] = []

    # ── At least one table ─────────────────────────────────────────────
    if not decisions.tables:
        failures.append("No tables produced by LLM")
        return failures  # No point checking further

    # ── Every table has columns (unless calc group) ────────────────────
    for table in decisions.tables:
        if not table.is_calc_group and not table.columns:
            failures.append(f"Table '{table.name}' has no columns")

    # ── Every regular table has an M query ─────────────────────────────
    for table in decisions.tables:
        if not table.is_calc_group and not table.m_query.strip():
            failures.append(f"Table '{table.name}' has empty M query")

    # ── M queries have let/in structure ────────────────────────────────
    for table in decisions.tables:
        if table.is_calc_group or not table.m_query.strip():
            continue
        m = table.m_query.strip().lower()
        if "let" not in m or "in" not in m:
            failures.append(f"Table '{table.name}' M query missing let/in structure")

    # ── Relationships reference valid tables ───────────────────────────
    table_names = {t.name for t in decisions.tables}
    for rel in decisions.relationships:
        if rel.from_table not in table_names:
            failures.append(f"Relationship from_table '{rel.from_table}' " f"not in table set")
        if rel.to_table not in table_names:
            failures.append(f"Relationship to_table '{rel.to_table}' " f"not in table set")

    # ── Relationship columns exist in their tables ─────────────────────
    table_columns: dict[str, set[str]] = {}
    for table in decisions.tables:
        table_columns[table.name] = {c.name for c in table.columns}
        # Also check by source_column since relationships may use either
        table_columns[table.name] |= {c.source_column for c in table.columns}

    for rel in decisions.relationships:
        if rel.from_table in table_columns:
            if rel.from_column not in table_columns[rel.from_table]:
                failures.append(f"Relationship column '{rel.from_column}' " f"not found in table '{rel.from_table}'")
        if rel.to_table in table_columns:
            if rel.to_column not in table_columns[rel.to_table]:
                failures.append(f"Relationship column '{rel.to_column}' " f"not found in table '{rel.to_table}'")

    # ── source_query_culture is non-empty ──────────────────────────────
    if not decisions.source_query_culture.strip():
        failures.append("source_query_culture is empty")

    # ── Datasource coverage: every input datasource has a table ────────
    input_ds_names = {ds.get("name", ds.get("caption", "")) for ds in input_metadata.get("datasources", [])}
    if input_ds_names and not decisions.tables:
        failures.append(f"Input has {len(input_ds_names)} datasource(s) but " f"LLM produced no tables")

    return failures


# ═══════════════════════════════════════════════════════════════════════════
#  DAX Measures (Stage 4)
# ═══════════════════════════════════════════════════════════════════════════


def validate_dax_measures_structure(measures_tmdl: str) -> list[str]:
    """Check structural invariants on the generated TMDL measures.

    Args:
        measures_tmdl: The raw TMDL content from the LLM.

    Returns:
        A list of failure descriptions.
    """
    failures: list[str] = []

    if not measures_tmdl.strip():
        failures.append("TMDL content is empty")
        return failures

    # Should contain at least one measure declaration
    if "measure" not in measures_tmdl.lower():
        failures.append("TMDL contains no 'measure' keyword")

    # TMDL indentation should use tabs, not spaces (PBI convention)
    lines = measures_tmdl.split("\n")
    indented_lines = [ln for ln in lines if ln and ln[0] in (" ", "\t")]
    if indented_lines:
        space_indented = sum(1 for ln in indented_lines if ln[0] == " ")
        if space_indented > len(indented_lines) * 0.5:
            failures.append("TMDL uses space indentation — should use TABs")

    # Check for basic DAX syntax: should contain '=' for measure expressions
    if "=" not in measures_tmdl:
        failures.append("TMDL contains no '=' — likely missing measure expressions")

    return failures


# ═══════════════════════════════════════════════════════════════════════════
#  PBIR Report (Stage 5)
# ═══════════════════════════════════════════════════════════════════════════

# Required file paths that every valid PBIR output must contain.
_REQUIRED_REPORT_PATHS = {
    "definition/report.json",
    "definition/version.json",
}


def validate_report_structure(files: dict[str, str]) -> list[str]:
    """Check structural invariants on the generated PBIR report files.

    Args:
        files: Mapping of relative paths to file content strings.

    Returns:
        A list of failure descriptions.
    """
    failures: list[str] = []

    if not files:
        failures.append("Report output contains no files")
        return failures

    # ── Required paths present ─────────────────────────────────────────
    # Normalise to forward-slash for comparison
    normalised_keys = {k.replace("\\", "/") for k in files}
    for required in _REQUIRED_REPORT_PATHS:
        if required not in normalised_keys:
            failures.append(f"Missing required report file: {required}")

    # ── JSON files parse correctly ─────────────────────────────────────
    for path, content in files.items():
        if path.endswith(".json"):
            try:
                json.loads(content)
            except (json.JSONDecodeError, TypeError):
                failures.append(f"Invalid JSON in: {path}")

    # ── report.json has basic structure ────────────────────────────────
    report_json_content = files.get("definition/report.json")
    if report_json_content:
        try:
            report = json.loads(report_json_content)
            if not isinstance(report, dict):
                failures.append("report.json is not a JSON object")
        except (json.JSONDecodeError, TypeError):
            pass  # Already reported above

    return failures
