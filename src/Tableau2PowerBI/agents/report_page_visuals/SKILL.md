---
name: report-page-visuals
description: Generate visual.json content for all visuals on a single Power BI report page.
---

# SKILL: Page Visual Content Generator

## Overview

You generate the `visual.json` file content for each visual on a **single** Power BI
report page. You receive:

- A skeleton manifest for this page (visual hex IDs, types, positions)
- Filtered Tableau worksheet metadata (only worksheets on this page)
- The Power BI semantic model schema

For each visual slot in the skeleton, produce a complete `visual.json` following the
PBIR v4.0 `visualContainer/2.7.0` schema.

---

## Input

### Skeleton page

The skeleton provides pre-computed information for each visual:

```json
{
  "dashboard_name": "Clienti",
  "display_name": "Clienti",
  "hex_id": "a3f8c91b2e4d07a6c1e0",
  "visuals": [
    {
      "worksheet_name": "Dispersione cliente",
      "visual_type": "scatterChart",
      "hex_id": "b7d2e1f094a38c5b6d21",
      "position": { "x": 5, "y": 95, "width": 600, "height": 400, "tab_order": 0 }
    }
  ]
}
```

Use the skeleton's `visual_type`, `hex_id`, and `position` **exactly** as provided.
Your job is to fill in the `visual.query`, `drillFilterOtherVisuals`, and `filterConfig`.

### Visual metadata (TDD field_bindings format)

Each visual in the input has pre-resolved `field_bindings` from the Target Technical
Documentation. These already contain the correct Power BI table, field name, field kind,
aggregation, and target well. **Use them directly** — they are the source of truth.

```json
{
  "worksheet_name": "Panoramica clienti",
  "visual_type": "tableEx",
  "field_bindings": [
    {
      "tableau_field": "[Regione]",
      "pbi_table": "Ordini",
      "pbi_field": "Regione",
      "field_kind": "Column",
      "aggregation": "none",
      "well": "Category"
    },
    {
      "tableau_field": "[Profitto]",
      "pbi_table": "Ordini",
      "pbi_field": "Profitto",
      "field_kind": "Aggregation",
      "aggregation": "sum",
      "well": "Values"
    },
    {
      "tableau_field": "[Calculation_9921103144103743]",
      "pbi_table": "Ordini",
      "pbi_field": "Rapporto profitto",
      "field_kind": "Measure",
      "aggregation": "none",
      "well": "Values"
    }
  ],
  "filters": [...],
  "sort_specs": [...],
  "notes": "..."
}
```

**How to use field_bindings:**

- `pbi_table` → the `Entity` in PBIR `SourceRef`
- `pbi_field` → the `Property` in PBIR field references
- `field_kind` → determines the JSON structure:
  - `"Column"` → use `Column` field type
  - `"Aggregation"` → use `Aggregation` field type with nested `Expression.Column`
  - `"Measure"` → use `Measure` field type
- `aggregation` → for `Aggregation` kind, maps to `Function` enum (see below)
- `well` → the Power BI query role to assign this field to (e.g. `"Category"`,
  `"Values"`, `"X"`, `"Y"`, `"Legend"`, `"Rows"`, `"Columns"`, etc.)
  - **Exception for tableEx:** all fields go into `"Values"` regardless of `well`
  - **Exception for scatterChart:** use `"X"`/`"Y"` for measures instead of `"Values"`

Match visuals by `worksheet_name` between the skeleton and the visual metadata.

### Legacy worksheet format (backward compatibility)

If the input has `worksheets` instead of `visuals`, use the legacy format:

**Important:**
- All worksheet arrays (`cols_shelf`, `rows_shelf`, `encodings`, `filters`,
  `sorts`, `reference_lines`, `table_calculations`) are optional — default to `[]`.
- **Skip empty shelf objects `{}`** — they are structural placeholders.
- **`:Measure Names`** in shelves is a structural indicator, not a real field.

### Datasource index

The `datasource_index` maps Tableau datasource federation IDs to human-readable
Tableau datasource names. These are **NOT Power BI table names** — always use the
table names from the semantic model schema for `Entity` references.

### Semantic model schema

Lists the Power BI tables, columns, and measures. Always use these exact names for
`Entity` and `Property` fields — never Tableau datasource names.

If a "Tableau calculated field → Power BI measure name mapping" section is present,
use it to resolve `Calculation_XXXXXXXXX` references.

---

## visual.json specification

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.7.0/schema.json",
  "name": "<VisualHexId from skeleton>",
  "position": {
    "x": "<from skeleton>",
    "y": "<from skeleton>",
    "z": 0,
    "width": "<from skeleton>",
    "height": "<from skeleton>",
    "tabOrder": "<from skeleton.tab_order>"
  },
  "visual": {
    "visualType": "<from skeleton.visual_type>",
    "query": {
      "queryState": {
        "<role>": {
          "projections": [ ... ]
        }
      }
    },
    "drillFilterOtherVisuals": true
  },
  "filterConfig": {
    "filters": [ ... ]
  }
}
```

**CRITICAL nesting rules — the PBIR schema is strict about property placement:**
- `drillFilterOtherVisuals` goes under `visual` (NOT under `visual.query`)
- `filterConfig` goes at the **root** of the visual container (sibling of `visual`)
- `query` goes under `visual` and contains ONLY `queryState`

---

## Field kind — Column vs Aggregation vs Measure

PBIR uses THREE field kinds. Getting this wrong causes missing references in Power BI.

| Kind | When to use | JSON structure |
|---|---|---|
| `Column` | Non-aggregated dimension fields (Tableau agg `none`, `yr`, `mn`, `qr`, date parts, `null`) | `{"Column": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "F"}}` |
| `Aggregation` | Physical columns WITH aggregation (`sum`, `avg`, `min`, `max`, `count`, `countd`, `median`) | `{"Aggregation": {"Expression": {"Column": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "F"}}, "Function": N}}` |
| `Measure` | DAX measures ONLY (from schema's Measures section or resolved Calculation_XXX) | `{"Measure": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "F"}}` |

**Aggregation Function enum:**

| Code | Function |
|---|---|
| 0 | Sum |
| 1 | Avg |
| 2 | Count |
| 3 | Min |
| 4 | Max |
| 5 | CountNonNull |
| 6 | Median |

### How to determine field kind (priority order)

1. If the field is in the schema's `Measures` list → `Measure`
2. If the field is a `Column` AND Tableau aggregation is `none`/`null`/date-part → `Column`
3. If the field is a `Column` AND Tableau aggregation is `sum`/`avg`/etc. → `Aggregation`
4. If `Calculation_XXXXXXXXX` resolved to a PBI measure → `Measure`
5. Default → `Column`

**CRITICAL:** A physical column like `Vendite` or `Profitto` is NEVER a `Measure` in
PBIR, even when Tableau aggregates it. Use `Aggregation` for aggregated physical columns,
and `Measure` ONLY for DAX measures.

### queryRef and nativeQueryRef format

| Kind | queryRef | nativeQueryRef |
|---|---|---|
| Column | `"Table.Column"` | `"Column"` |
| Aggregation | `"Sum(Table.Column)"` | `"Sum of Column"` |
| Measure | `"Table.Measure"` | `"Measure"` |

### Concrete examples

**Column (non-aggregated):**
```json
{
  "field": {
    "Column": {
      "Expression": { "SourceRef": { "Entity": "Ordini" } },
      "Property": "Regione"
    }
  },
  "queryRef": "Ordini.Regione",
  "nativeQueryRef": "Regione",
  "active": true
}
```

**Aggregation (Sum of physical column):**
```json
{
  "field": {
    "Aggregation": {
      "Expression": {
        "Column": {
          "Expression": { "SourceRef": { "Entity": "Ordini" } },
          "Property": "Vendite"
        }
      },
      "Function": 0
    }
  },
  "queryRef": "Sum(Ordini.Vendite)",
  "nativeQueryRef": "Sum of Vendite",
  "active": true
}
```

**Measure (DAX):**
```json
{
  "field": {
    "Measure": {
      "Expression": { "SourceRef": { "Entity": "Ordini" } },
      "Property": "Total Sales"
    }
  },
  "queryRef": "Ordini.Total Sales",
  "nativeQueryRef": "Total Sales",
  "active": true
}
```

---

## Field role mapping per visual type

### barChart / columnChart / lineChart / areaChart / donutChart

| Tableau source | Power BI role |
|---|---|
| Dimension field (cols/rows with no aggregation) | `"Category"` |
| Aggregated measure (cols/rows with sum/avg/etc.) | `"Values"` |
| Encoding `type=interpolated` or `custom-interpolated` | `"Color"` |
| Encoding `type=centersize` | `"Size"` |
| Encoding `type=space` | `"Details"` |

### scatterChart

| Tableau source | Power BI role |
|---|---|
| First aggregated measure | `"X"` |
| Second aggregated measure | `"Y"` |
| Dimension field | `"Legend"` |
| Encoding `type=centersize` | `"Size"` |
| Encoding `type=interpolated` | `"Color"` |

**NEVER use `"Values"` for scatterChart — use `"X"` and `"Y"` only.**

### matrixVisual

| Tableau source | Power BI role |
|---|---|
| Row dimensions | `"Rows"` |
| Column dimensions | `"Columns"` |
| Measures | `"Values"` |

**NEVER use `"Category"`, `"Color"`, or `"Size"` for matrixVisual.**

### tableEx

| Tableau source | Power BI role |
|---|---|
| All fields | `"Values"` |

**ALL fields in a tableEx go into `"Values"`. Never use `"Category"` for tableEx.**

### map

| Tableau source | Power BI role |
|---|---|
| Geographic dimension | `"Location"` |
| Size measure | `"Size"` |
| Color measure | `"Color"` |
| Latitude (generated) | `"Latitude"` |
| Longitude (generated) | `"Longitude"` |

### multiRowCard

| Tableau source | Power BI role |
|---|---|
| All measures and dimensions | `"Values"` |

If `:Measure Names` is the only shelf entry, project all available measures from
the schema into `"Values"`.

### General rules

- `:Measure Names` → skip (structural indicator, not a real field)
- Empty shelf objects `{}` → skip

---

## filterConfig

Every visual MUST include a `filterConfig.filters` array at the **root level**
of the visual container (sibling of `visual` and `position`, NOT nested inside `visual`):

```json
{
  "filterConfig": {
    "filters": [
      {
        "name": "<20-char-hex-id>",
        "field": { "Column": { "Expression": { "SourceRef": { "Entity": "T" } }, "Property": "F" } },
        "type": "Categorical"
      }
    ]
  }
}
```

- `name`: deterministic 20-char lowercase hex, unique per filter
- `Column` fields → `type: "Categorical"`
- `Aggregation` and `Measure` fields → `type: "Advanced"`

Include one filter entry per field used in the visual's `queryState`.

**Aggregation in filterConfig example:**
```json
{
  "name": "fd2ab940f844985ffb79",
  "field": {
    "Aggregation": {
      "Expression": {
        "Column": {
          "Expression": { "SourceRef": { "Entity": "Ordini" } },
          "Property": "Vendite"
        }
      },
      "Function": 0
    }
  },
  "type": "Advanced"
}
```

---

## Calculated field handling

Calculated fields appear as `Calculation_XXXXXXXXX` in field names. A
**Tableau → Power BI name mapping** is provided in the prompt under
"Tableau calculated field → Power BI measure name mapping":

1. Look up the calculation ID in the mapping
2. If found → use the PBI measure name as `Property`, use `Measure` as field kind
3. If NOT found → use the calc ID as-is, emit `CALC_FIELD_UNRESOLVED` warning
4. Use the correct Power BI table from the schema as the `Entity`

---

## Shelf entry formats

Shelf entries appear in several formats:

1. **Standard field:**
   ```json
   { "aggregation": "sum", "field": "Vendite", "type_code": "qk" }
   ```

2. **Measure Names pseudo-field:**
   ```json
   { "field": ":Measure Names" }
   ```
   Skip — structural indicator, not a real field projection.

3. **Computed percentage:**
   ```json
   { "field": "pcto:cnt:Ordini_XXXX:qk:1" }
   ```
   Use the field name portion and emit `COMPUTED_FIELD_APPROX` warning.

4. **Generated geo fields:**
   ```json
   { "aggregation": null, "field": "Longitude (generated)", "type_code": null }
   ```

5. **Empty object:** `{}` — skip entirely.

---

## Warnings

Emit warnings for:

| Code | When |
|---|---|
| `TABLE_CALC_NOT_SUPPORTED` | Worksheet has non-empty `table_calculations` |
| `REFERENCE_LINE_NOT_SUPPORTED` | Worksheet has non-empty `reference_lines` |
| `CALC_FIELD_UNRESOLVED` | `Calculation_XXX` not found in mapping |
| `COMPUTED_FIELD_APPROX` | `pcto:` field format |

Deduplicate: emit each `CALC_FIELD_UNRESOLVED` only once per calculation ID.

---

## Common Mistakes — WRONG → RIGHT

### 1. `filterConfig` nested inside `visual`
**WRONG:** `{ "visual": { "filterConfig": {...} } }`
**RIGHT:** `filterConfig` is a sibling of `visual` at the root.

### 2. `drillFilterOtherVisuals` inside `visual.query`
**WRONG:** `{ "visual": { "query": { "drillFilterOtherVisuals": true } } }`
**RIGHT:** `drillFilterOtherVisuals` goes under `visual`, NOT `visual.query`:
```json
{ "visual": { "query": { "queryState": {...} }, "drillFilterOtherVisuals": true } }
```

### 3. `visual.config` present
**WRONG:** `{ "visual": { "config": "..." } }`
**RIGHT:** Omit `config` entirely — it is a legacy PBIX property.

### 4. Using `Measure` for aggregated physical columns
**WRONG:** `{ "Measure": { "Property": "Vendite" } }` when Vendite is a column with `sum`
**RIGHT:** Use `Aggregation` with nested `Expression.Column` and `Function: 0`.

### 5. Using raw `Calculation_XXXXXXXXX` as Property
**WRONG:** `"Property": "Calculation_9921103144103743"`
**RIGHT:** Look up and use the PBI measure name from the mapping.

### 6. Using `"Values"` for scatterChart
**WRONG:** scatterChart with `"Values"` role.
**RIGHT:** Use `"X"` and `"Y"` roles for measures.

### 7. Using `"Category"` for tableEx or matrixVisual
**WRONG:** tableEx with `"Category"` role.
**RIGHT:** tableEx uses `"Values"` for ALL fields. matrixVisual uses `"Rows"`/`"Columns"`/`"Values"`.

### 8. Missing `active: true` on projections
Every projection MUST have `"active": true`.

### 9. queryState role as bare array instead of object
**WRONG:** `"Category": [{ "field": {...}, "queryRef": "..." }]`
**RIGHT:** Each queryState role MUST be an **object** with a `"projections"` key:
```json
"Category": { "projections": [{ "field": {...}, "queryRef": "..." }] }
```
Power BI rejects `"Expected Object but got Array"` when the role value is a bare array.

---

## Output Format

Return a single JSON object — no markdown fences, no preamble. Each key is a visual
hex_id from the skeleton. Each value is the **complete** visual.json content as a
compact JSON string:

```json
{
  "b7d2e1f094a38c5b6d21": "{\"$schema\":\"https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.7.0/schema.json\",\"name\":\"b7d2e1f094a38c5b6d21\",\"position\":{\"x\":5,\"y\":95,\"z\":0,\"width\":600,\"height\":400,\"tabOrder\":0},\"visual\":{\"visualType\":\"scatterChart\",\"query\":{\"queryState\":{...}},\"drillFilterOtherVisuals\":true},\"filterConfig\":{\"filters\":[...]}}",
  "_warnings": []
}
```

### CRITICAL — compactness

- File content values MUST be compact single-line JSON strings (no indentation)
- Double quotes inside values must be escaped as `\"`
- Backslashes must be escaped as `\\` — a stray `\` kills JSON parsing
- No literal newlines or tabs inside string values
- Include `_warnings` even if empty: `"_warnings": []`
- The entire response must be parseable by a single `json.loads()` call

### Self-check

- [ ] Every visual hex_id from the skeleton has a corresponding entry
- [ ] Each visual.json has `$schema`, `name`, `position`, `visual`, `filterConfig`
- [ ] `name` matches the visual hex_id
- [ ] `position` matches the skeleton values exactly (include `z: 0`)
- [ ] `visualType` matches the skeleton's `visual_type`
- [ ] `drillFilterOtherVisuals: true` under `visual` (NOT under `query`)
- [ ] `filterConfig` at root level (NOT under `visual`)
- [ ] No `visual.config` property
- [ ] Physical columns with aggregation use `Aggregation` (NOT `Measure`)
- [ ] Only DAX measures use the `Measure` field kind
- [ ] `queryRef` and `nativeQueryRef` follow the correct format per field kind
- [ ] Entity names come from the semantic model schema, not Tableau
- [ ] Every projection has `active: true`
- [ ] Output is valid JSON, no markdown fences
