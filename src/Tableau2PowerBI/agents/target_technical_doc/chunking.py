"""Chunked-batch helpers for the Target Technical Documentation agent.

When the full TDD prompt exceeds the configured token budget, the agent
splits the variable-size input (datasources for Call 1, dashboards for
Call 2) into smaller batches that each fit within the budget.  The LLM
is called once per batch and partial results are merged deterministically.

Token estimation uses a simple bytes-to-tokens heuristic — accurate
enough for budget decisions without requiring a tokeniser dependency.
"""

from __future__ import annotations

import logging
from typing import Any

from Tableau2PowerBI.agents.target_technical_doc.models import (
    AssessmentWarning,
    DataModelDesign,
    DaxMeasuresDesign,
    EntityResolutionMap,
    MigrationAssessment,
    ReportDesign,
    SemanticModelDesign,
)
from Tableau2PowerBI.core.prompt_utils import compact_json

# ── Token estimation ──────────────────────────────────────────────────

_BYTES_PER_TOKEN: int = 4
"""Approximate number of UTF-8 bytes per token for GPT-class models.

This is a deliberately conservative estimate (real averages are ~3.5–4.2
for English text, higher for structured JSON).  Using 4 means we
slightly over-estimate token counts, which is safer than under-counting
because it reduces the chance of hitting a context-length error at
call time.
"""


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in *text* using a bytes heuristic.

    Args:
        text: The string to estimate.

    Returns:
        Estimated token count (always >= 0).
    """
    return len(text.encode("utf-8")) // _BYTES_PER_TOKEN


# ── Batch builders ────────────────────────────────────────────────────

def build_datasource_batches(
    sm_input: dict,
    budget_tokens: int,
    fixed_tokens: int,
) -> list[dict]:
    """Split *sm_input* datasources into token-budget-fitting batches.

    Each batch is a dict with keys ``"datasources"`` (a non-empty list)
    and ``"parameters"`` (included only in the **first** batch to avoid
    wasting tokens repeating them).

    Args:
        sm_input: The full ``semantic_model_input.json`` dict.  Expected
            to contain a ``"datasources"`` list and optionally a
            ``"parameters"`` list.
        budget_tokens: Maximum tokens allowed for the variable portion
            of the prompt (total budget minus fixed overhead).
        fixed_tokens: Tokens already consumed by the fixed parts of the
            prompt (prefix, section headers, func_doc).

    Returns:
        A list of batch dicts, each fitting within the budget.

    Raises:
        RuntimeError: If any single datasource alone exceeds the budget.
    """
    datasources: list[dict] = sm_input.get("datasources", [])
    parameters: list[dict] = sm_input.get("parameters", [])

    if not datasources:
        # Nothing to split — return a single batch with whatever we have
        return [{"datasources": [], "parameters": parameters}]

    available_tokens = budget_tokens - fixed_tokens
    # Token cost of parameters (only counted against the first batch)
    params_json = compact_json(parameters) if parameters else "[]"
    params_tokens = estimate_tokens(params_json)

    batches: list[dict] = []
    current_ds: list[dict] = []
    # The first batch must also fit the parameters, so start its running
    # total at params_tokens.  Subsequent batches reset to 0.
    current_tokens = params_tokens
    is_first_batch = True

    for ds in datasources:
        ds_json = compact_json(ds)
        ds_tokens = estimate_tokens(ds_json)

        # Check if a single datasource alone exceeds the budget
        first_batch_overhead = params_tokens if is_first_batch else 0
        if ds_tokens + first_batch_overhead > available_tokens:
            raise RuntimeError(
                f"Single datasource '{ds.get('name', '?')}' requires "
                f"~{ds_tokens} tokens but budget allows only "
                f"~{available_tokens - first_batch_overhead}. "
                f"Cannot split further."
            )

        if current_ds and (current_tokens + ds_tokens > available_tokens):
            # Flush current batch
            batch: dict[str, Any] = {"datasources": current_ds}
            if is_first_batch:
                batch["parameters"] = parameters
                is_first_batch = False
            batches.append(batch)
            current_ds = []
            current_tokens = 0  # subsequent batches do not carry params overhead

        current_ds.append(ds)
        current_tokens += ds_tokens

    # Flush remaining
    if current_ds:
        batch = {"datasources": current_ds}
        if is_first_batch:
            batch["parameters"] = parameters
        batches.append(batch)

    return batches


def build_dashboard_batches(
    report_input: dict,
    budget_tokens: int,
    fixed_tokens: int,
) -> list[dict]:
    """Split *report_input* dashboards into token-budget-fitting batches.

    Every batch includes the full ``datasource_index`` and ``datasources``
    (calculated fields) because the LLM needs them to resolve field
    bindings.  Only worksheets referenced by the batch's dashboards are
    included, and only actions whose ``source_dashboard`` matches a
    dashboard in the batch.

    Standalone worksheets (not referenced by any dashboard) are appended
    to the **last** batch.

    Args:
        report_input: The full ``report_input.json`` dict.
        budget_tokens: Maximum tokens for the variable portion.
        fixed_tokens: Tokens consumed by fixed prompt parts.

    Returns:
        A list of batch dicts.

    Raises:
        RuntimeError: If any single dashboard alone exceeds the budget.
    """
    dashboards: list[dict] = report_input.get("dashboards", [])
    all_worksheets: list[dict] = report_input.get("worksheets", [])
    all_actions: list[dict] = report_input.get("actions", [])
    datasource_index: dict = report_input.get("datasource_index", {})
    datasources: list[dict] = report_input.get("datasources", [])
    standalone_worksheets: list[str] = report_input.get("standalone_worksheets", [])

    # Build worksheet lookup by name for filtering
    ws_by_name: dict[str, dict] = {
        ws.get("name", ""): ws for ws in all_worksheets
    }

    # Shared context included in every batch
    shared_context: dict[str, Any] = {
        "datasource_index": datasource_index,
        "datasources": datasources,
    }
    shared_tokens = estimate_tokens(compact_json(shared_context))

    available_tokens = budget_tokens - fixed_tokens

    if not dashboards:
        # No dashboards — single batch with standalone worksheets
        batch: dict[str, Any] = {
            **shared_context,
            "dashboards": [],
            "worksheets": all_worksheets,
            "actions": all_actions,
            "standalone_worksheets": standalone_worksheets,
        }
        return [batch]

    batches: list[dict] = []
    current_dbs: list[dict] = []
    current_tokens = shared_tokens

    def _worksheets_for_dashboards(dbs: list[dict]) -> list[dict]:
        """Return only worksheets referenced by the given dashboards."""
        referenced: set[str] = set()
        for db in dbs:
            referenced.update(db.get("sheets", []))
        return [ws_by_name[name] for name in referenced if name in ws_by_name]

    def _actions_for_dashboards(dbs: list[dict]) -> list[dict]:
        """Return only actions whose source_dashboard is in this batch."""
        db_names = {db.get("name", "") for db in dbs}
        return [a for a in all_actions if a.get("source_dashboard", "") in db_names]

    def _flush_batch(dbs: list[dict]) -> dict[str, Any]:
        """Build a batch dict from the given dashboards."""
        return {
            **shared_context,
            "dashboards": dbs,
            "worksheets": _worksheets_for_dashboards(dbs),
            "actions": _actions_for_dashboards(dbs),
        }

    for db in dashboards:
        # Estimate tokens for this dashboard + its worksheets
        db_ws = _worksheets_for_dashboards([db])
        db_actions = _actions_for_dashboards([db])
        db_payload = compact_json({
            "dashboard": db,
            "worksheets": db_ws,
            "actions": db_actions,
        })
        db_tokens = estimate_tokens(db_payload)

        # Check if single dashboard exceeds budget
        if db_tokens + shared_tokens > available_tokens:
            raise RuntimeError(
                f"Single dashboard '{db.get('name', '?')}' requires "
                f"~{db_tokens + shared_tokens} tokens but budget allows "
                f"only ~{available_tokens}. Cannot split further."
            )

        if current_dbs and (current_tokens + db_tokens > available_tokens):
            # Flush current batch
            batches.append(_flush_batch(current_dbs))
            current_dbs = []
            current_tokens = shared_tokens

        current_dbs.append(db)
        current_tokens += db_tokens

    # Flush remaining dashboards
    if current_dbs:
        last_batch = _flush_batch(current_dbs)
        # Standalone worksheets go into the last batch
        if standalone_worksheets:
            last_batch["standalone_worksheets"] = standalone_worksheets
            # Add standalone worksheet data
            standalone_ws = [
                ws_by_name[name]
                for name in standalone_worksheets
                if name in ws_by_name
            ]
            last_batch["worksheets"] = last_batch["worksheets"] + standalone_ws
        batches.append(last_batch)

    return batches


# ── Merge functions ───────────────────────────────────────────────────

# Explicit ordering for complexity_score comparison.
_COMPLEXITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def merge_data_model_results(
    partials: list[DataModelDesign],
    log: logging.Logger,
) -> DataModelDesign:
    """Deterministically merge partial DataModelDesign results from batches.

    Tables, measures, parameters are deduplicated by name (first
    occurrence wins).  Relationships are concatenated without dedup
    since different batches may contribute different relationships.
    Assessment fields are merged: warnings deduplicated by code,
    complexity_score takes the maximum, manual_items concatenated.

    Args:
        partials: List of DataModelDesign results from each batch.
        log: Logger for merge diagnostics.

    Returns:
        A single merged DataModelDesign.
    """
    if len(partials) == 1:
        return partials[0]

    log.info("Merging %d data model batch results", len(partials))

    # Tables — deduplicate by name (first occurrence wins)
    seen_tables: set[str] = set()
    merged_tables = []
    for partial in partials:
        for table in partial.semantic_model.tables:
            if table.name not in seen_tables:
                seen_tables.add(table.name)
                merged_tables.append(table)

    # Relationships — concatenate all (no dedup)
    merged_rels = []
    for partial in partials:
        merged_rels.extend(partial.semantic_model.relationships)

    # Parameters — deduplicate by name (first occurrence wins)
    seen_params: set[str] = set()
    merged_params = []
    for partial in partials:
        for param in partial.semantic_model.parameters:
            if param.name not in seen_params:
                seen_params.add(param.name)
                merged_params.append(param)

    # source_query_culture — take from first partial
    sqc = partials[0].semantic_model.source_query_culture

    semantic_model = SemanticModelDesign(
        tables=merged_tables,
        relationships=merged_rels,
        parameters=merged_params,
        source_query_culture=sqc,
    )

    # Measures — deduplicate by tableau_name (first occurrence wins)
    seen_measures: set[str] = set()
    merged_measures = []
    for partial in partials:
        for measure in partial.dax_measures.measures:
            if measure.tableau_name not in seen_measures:
                seen_measures.add(measure.tableau_name)
                merged_measures.append(measure)

    # Untranslatable — deduplicate by tableau_name
    seen_untrans: set[str] = set()
    merged_untrans = []
    for partial in partials:
        for item in partial.dax_measures.untranslatable:
            if item.tableau_name not in seen_untrans:
                seen_untrans.add(item.tableau_name)
                merged_untrans.append(item)

    dax_measures = DaxMeasuresDesign(
        measures=merged_measures,
        untranslatable=merged_untrans,
    )

    # Assessment — merge warnings (dedup by code), max complexity, concat manual_items
    seen_warning_codes: set[str] = set()
    merged_warnings: list[AssessmentWarning] = []
    merged_manual: list[str] = []
    max_complexity = "low"

    for partial in partials:
        for w in partial.assessment.warnings:
            if w.code not in seen_warning_codes:
                seen_warning_codes.add(w.code)
                merged_warnings.append(w)
        merged_manual.extend(partial.assessment.manual_items)
        if _COMPLEXITY_ORDER.get(partial.assessment.complexity_score, 0) > _COMPLEXITY_ORDER.get(max_complexity, 0):
            max_complexity = partial.assessment.complexity_score

    # Summary — take the longest (most detailed) summary
    summary = max((p.assessment.summary for p in partials), key=len, default="")

    assessment = MigrationAssessment(
        complexity_score=max_complexity,
        summary=summary,
        warnings=merged_warnings,
        manual_items=merged_manual,
    )

    log.info(
        "Merged: %d tables, %d measures, %d relationships",
        len(merged_tables),
        len(merged_measures),
        len(merged_rels),
    )

    return DataModelDesign(
        semantic_model=semantic_model,
        dax_measures=dax_measures,
        assessment=assessment,
    )


def merge_report_results(
    partials: list[ReportDesign],
    log: logging.Logger,
) -> ReportDesign:
    """Deterministically merge partial ReportDesign results from batches.

    Pages are concatenated and re-assigned sequential ``page_order``
    values (0, 1, 2, ...) in the order they appear across batches.
    Entity resolution dicts are unioned with conflict warnings.
    Standalone worksheets are unioned without duplicates.

    Args:
        partials: List of ReportDesign results from each batch.
        log: Logger for merge diagnostics.

    Returns:
        A single merged ReportDesign.
    """
    if len(partials) == 1:
        return partials[0]

    log.info("Merging %d report batch results", len(partials))

    # Pages — concatenate all, then re-assign page_order sequentially
    merged_pages = []
    for partial in partials:
        merged_pages.extend(partial.pages)

    for idx, page in enumerate(merged_pages):
        page.page_order = idx

    # Standalone worksheets — set union preserving insertion order
    seen_ws: set[str] = set()
    merged_standalone: list[str] = []
    for partial in partials:
        for ws in partial.standalone_worksheets:
            if ws not in seen_ws:
                seen_ws.add(ws)
                merged_standalone.append(ws)

    # Entity resolution — union with conflict warnings
    merged_ds_to_table: dict[str, str] = {}
    merged_calc_map: dict[str, str] = {}

    for partial in partials:
        er = partial.entity_resolution
        for key, value in er.datasource_to_table.items():
            if key in merged_ds_to_table and merged_ds_to_table[key] != value:
                log.warning(
                    "entity_resolution conflict: datasource_to_table[%r] "
                    "maps to %r and %r — keeping first",
                    key,
                    merged_ds_to_table[key],
                    value,
                )
            else:
                merged_ds_to_table[key] = value

        for key, value in er.calculated_field_map.items():
            if key in merged_calc_map and merged_calc_map[key] != value:
                log.warning(
                    "entity_resolution conflict: calculated_field_map[%r] "
                    "maps to %r and %r — keeping first",
                    key,
                    merged_calc_map[key],
                    value,
                )
            else:
                merged_calc_map[key] = value

    entity_resolution = EntityResolutionMap(
        datasource_to_table=merged_ds_to_table,
        calculated_field_map=merged_calc_map,
    )

    log.info(
        "Merged: %d pages, %d standalone worksheets",
        len(merged_pages),
        len(merged_standalone),
    )

    return ReportDesign(
        pages=merged_pages,
        standalone_worksheets=merged_standalone,
        entity_resolution=entity_resolution,
    )
