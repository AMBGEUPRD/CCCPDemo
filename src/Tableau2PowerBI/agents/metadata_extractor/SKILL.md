---
name: tableau-source-understanding
description: Generate canonical Tableau workbook inventory JSON from .twb or .twbx inputs using deterministic extraction and schema validation. Use for Tableau source understanding, metadata extraction, inventory generation, unsupported construct flagging, and ambiguity reporting before migration planning. Do not use for Tableau-to-Power BI conversion, semantic mapping, DAX generation, or report recreation.
---

# Tableau Source Understanding

## Mission

Produce a canonical, schema-valid `workbook_inventory.json` from Tableau workbook sources (`.twb` or `.twbx`).
Focus only on source understanding and inventory generation.

## Scope

In scope:
- Parse Tableau workbook XML from `.twb` and `.twbx`.
- Normalize output into canonical JSON contract.
- Extract workbook metadata, datasources, fields, calculations, parameters, worksheets, dashboards.
- Emit deterministic warnings for unsupported or ambiguous constructs.

Out of scope:
- Tableau-to-Power BI conversion logic.
- Mapping Tableau elements to Power BI entities.
- Any narrative recommendation that is not represented in the contract.

## Inputs And Outputs

Inputs:
- Tableau workbook file path ending in `.twb` or `.twbx`.

Output:
- `workbook_inventory.json` that conforms to `schemas/workbook_contract.schema.json`.

## Workflow

1. Detect input format.
2. If `.twbx`, unpack and resolve the primary `.twb`.
3. Parse workbook XML deterministically.
4. Extract canonical sections only:
   - `workbook`
   - `datasources`
   - `fields`
   - `calculations`
   - `parameters`
   - `worksheets`
   - `dashboards`
   - `warnings`
5. Validate contract against `schemas/workbook_contract.schema.json`.
6. Emit only schema-valid JSON. If validation fails, fix extraction output; do not emit relaxed shape.

## Operational Constraints

- Prefer schema-valid JSON over narrative text.
- Keep extraction logic thin and deterministic.
- Do not infer conversion intent or invent mappings.
- Preserve uncertainty as structured warnings.
- Keep top-level contract stable and versioned.

## Escalation Rules

Add entries to `warnings[]` for any unsupported or ambiguous workbook construct.
Each warning should include:
- `code`: machine-friendly identifier.
- `severity`: `info`, `warning`, or `error`.
- `message`: clear operator-facing explanation.
- `path`: XML or logical location when available.
- `manual_review_required`: `true` for unsupported/ambiguous constructs.

At minimum escalate:
- Unknown or unsupported Tableau structures.
- Missing identifiers required for canonical referencing.
- Calculation dependencies that cannot be resolved confidently.
- Multiple candidate workbook roots in packaged inputs.

## Assumptions

- Canonical contract version starts at `1.0.0`.
- `.twbx` contains at least one `.twb` file.
- Standard library XML parsing is sufficient for v1 extraction.
