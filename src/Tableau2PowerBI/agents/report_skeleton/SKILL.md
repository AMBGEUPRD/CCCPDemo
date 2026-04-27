---
name: report-skeleton
description: Generate a lightweight page/visual skeleton manifest for a Power BI report from Tableau metadata.
---

# SKILL: Report Skeleton Generator

## Overview

You parse Tableau report metadata and produce a **skeleton manifest** — a structured
JSON object that defines the report's page/visual layout without generating any file
content. For each Tableau dashboard you create a page entry, and for each worksheet
on that dashboard you create a visual slot with its type and position.

The skeleton is consumed by downstream agents that fill in the visual content.

---

## Input Structure (report_input.json)

The input JSON has these relevant top-level keys:

```json
{
  "datasource_index": { ... },
  "worksheets": [ ... ],
  "dashboards": [ ... ]
}
```

### Dashboards

Each dashboard object has:
- `name`: dashboard name (becomes the page display name)
- `size`: `{ "minwidth": "1000", "minheight": "620" }` (in Tableau units)
- `sheets`: list of worksheet names on this dashboard
- `layout_zones`: list of position entries (may be absent):
  ```json
  { "name": "worksheet name", "type": null, "x": "410", "y": "7368", "w": "99180", "h": "14912" }
  ```

### Worksheets

Each worksheet has:
- `name`: internal name
- `title`: optional display title (fall back to `name` if absent)
- `mark_type`: `"Automatic"`, `"Bar"`, `"Line"`, `"Circle"`, `"Square"`, `"Map"`,
  `"Text"`, `"Area"`, `"Multipolygon"`, `"Pie"`, `"Gantt"`, etc.
- `cols_shelf`, `rows_shelf`: lists of shelf entries (may be absent or contain `{}`)
- `encodings`: list of encoding entries (may be absent)
- `filters`, `sorts`, `reference_lines`, `table_calculations`: optional arrays

**Important:**
- All worksheet arrays are optional — default to `[]` if absent.
- **Skip empty shelf objects `{}`** — they are structural placeholders.
- **`:Measure Names`** in shelves is a structural indicator, not a real field.

---

## GUID Generation — 20-char Hex IDs

All page and visual folder IDs MUST be **20-character lowercase hex strings**
generated deterministically from the source name.

### Algorithm (pseudocode)

```
function generateHexId(name):
    hash = 0
    for i, char in enumerate(name):
        hash = (hash * 31 + charCode(char)) & 0xFFFFFFFFFFFFFFFF
    hexStr = lowercase(toHex(hash mod 16^20)).zeropad(20)
    return hexStr
```

The same input always produces the same hex ID.

---

## Visual Type Mapping

Map each worksheet's `mark_type` to a Power BI `visualType`:

| Tableau mark_type | Shelf / encoding pattern | Power BI visualType |
|---|---|---|
| `Automatic` | cols=measure, rows=dimension | `barChart` |
| `Automatic` | cols=dimension, rows=measure | `columnChart` |
| `Automatic` | both cols and rows = measures | `scatterChart` |
| `Automatic` | `:Measure Names` in cols only | `multiRowCard` |
| `Automatic` | `:Measure Names` + 3+ dim fields in rows | `tableEx` |
| `Automatic` | rows only, no cols, no `:Measure Names` | `tableEx` |
| `Automatic` | no measures, dimension-only | `barChart` |
| `Bar` | any | `barChart` |
| `Line` | any | `lineChart` |
| `Circle` | any | `scatterChart` |
| `Square` | cols=date, rows=dimension | `matrixVisual` |
| `Map` | any | `map` |
| `Multipolygon` | geo fields | `map` |
| `Text` | any | `tableEx` |
| `Pie` | any | `donutChart` |
| `Area` | any | `areaChart` |
| `Gantt` | any | `tableEx` |

**Detecting "Automatic" type:** When `mark_type = "Automatic"`, examine the shelves:
- If `cols_shelf` contains a `":Measure Names"` entry → `multiRowCard`
  UNLESS `rows_shelf` has 3+ dimension fields → `tableEx`
- If both cols and rows are aggregated measures → `scatterChart`
- If cols has dimension and rows has measure → `columnChart`
- If cols has measure and rows has dimension → `barChart`
- Fallback → `barChart`

**Geo detection:** If any shelf or encoding references `Longitude (generated)` or
`Latitude (generated)`, use `map` regardless of mark_type.

---

## Coordinate Conversion (5-step algorithm)

Convert Tableau layout_zone units to Power BI pixel positions:

**Step 1 — Units to pixels:**
```
px = round(units / 914.4 * 96)
```
Apply to every x, y, w, h of every layout_zone for this dashboard.

**Step 2 — Bounding box:**
```
canvas_w = max(x_px + w_px) over all zones
canvas_h = max(y_px + h_px) over all zones
```

**Step 3 — Scale factor:**
```
scale_factor = 1280 / max(canvas_w, 1280)
```

**Step 4 — Apply scale:**
```
final_x = round(x_px * scale_factor)
final_y = round(y_px * scale_factor)
final_w = round(w_px * scale_factor)
final_h = round(h_px * scale_factor)
```

**Step 5 — Page height:**
```
page_height = max(round(canvas_h * scale_factor), 720)
```
After all positions are computed, verify:
```
max_bottom = max(y_final + h_final) over all visuals
if max_bottom > page_height: page_height = max_bottom
```

**Default position** (no layout_zone for a worksheet): `x:0, y:0, width:400, height:300`.

**Worked example:**
- Zone: `x=410, y=7368, w=99180, h=14912`
- Step 1: `x=43, y=773, w=10406, h=1565`
- canvas_w = 43+10406 = 10449 → scale_factor = 1280/10449 = 0.1225
- Step 4: `x=5, y=95, w=1275, h=192`

---

## Orphaned Worksheets

Worksheets in `worksheets[]` but NOT in any dashboard's `sheets[]` must be
converted into standalone report pages.

For each orphaned worksheet:
- create one page with `dashboard_name` and `display_name` equal to worksheet name
- set page `width` to `1280` and `height` to `720`
- add one full-page visual using `visual_type: "tableEx"`
- use position `x:0, y:0, width:1280, height:720, tab_order:0`

Worksheets in a dashboard's `sheets[]` but NOT in `worksheets[]` should emit
a `WORKSHEET_NOT_FOUND` warning with a default visual slot (`visual_type: "barChart"`,
default position).

---

## Warnings

Emit warnings in the `warnings` array:

| Code | When |
|---|---|
| `WORKSHEET_NOT_FOUND` | Dashboard references a sheet not in worksheets array |
| `UNKNOWN_VISUAL_TYPE` | No matching Power BI type — defaulted to `tableEx` |
| `TABLE_CALC_NOT_SUPPORTED` | Worksheet has non-empty `table_calculations` |
| `REFERENCE_LINE_NOT_SUPPORTED` | Worksheet has non-empty `reference_lines` |

---

## Output Format

Return a **single JSON object** (no markdown fences, no preamble):

```json
{
  "pages": [
    {
      "dashboard_name": "original Tableau dashboard name",
      "display_name": "display title for the page",
      "hex_id": "a3f8c91b2e4d07a6c1e0",
      "width": 1280,
      "height": 900,
      "visuals": [
        {
          "worksheet_name": "original Tableau worksheet name",
          "visual_type": "barChart",
          "hex_id": "b7d2e1f094a38c5b6d21",
          "position": {
            "x": 5,
            "y": 95,
            "width": 400,
            "height": 300,
            "tab_order": 0
          }
        }
      ]
    }
  ],
  "warnings": []
}
```

### Rules

- One page per dashboard, in dashboard array order
- One visual per worksheet, in the order they appear in the dashboard's `sheets[]`
- One additional standalone page per orphaned worksheet, appended in `standalone_worksheets` order
- `display_name` = dashboard name (use `title` if available, fall back to `name`)
- `width` is always `1280`
- `height` is computed from Step 5 of coordinate conversion
- `tab_order` = 0-based index of the visual within its page
- All hex IDs are deterministic 20-char lowercase hex
- Warnings array may be empty but must always be present

### Self-check

- [ ] Every dashboard has a page entry
- [ ] Every worksheet in a dashboard's `sheets[]` has a visual entry
- [ ] Orphaned worksheets are migrated as standalone single-visual pages
- [ ] All hex IDs are exactly 20 lowercase hex characters
- [ ] Positions are converted using the 5-step algorithm
- [ ] Page height ≥ 720 and ≥ max(y + height) over all visuals
- [ ] Visual types match the mapping table
- [ ] Output is valid JSON, no markdown fences
