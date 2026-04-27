---
name: dax-measures
description: Translate Tableau calculated fields, measures, and parameters into Power BI DAX measures and emit a valid TMDL measures file for a PBIP project.
---

# SKILL: Tableau → Power BI TMDL Migration

## Overview

You are an expert migration agent. Your task is to:
1. Parse the Target Technical Design (TDD) `dax_measures_design` section
2. Translate all calculated fields, measures, and parameters into DAX using the TDD's translation strategies
3. Output a set of valid Power BI TMDL files for use in a PBIP (Power BI Project) structure

---

## Step 1 — Parse the TDD

The input is a Target Technical Design (TDD) `dax_measures_design` JSON with:

```
{
  "measures": [
    {
      "tableau_name": "...",       // original Tableau calculated field name
      "caption": "...",            // human-readable name → DAX measure name
      "formula": "...",            // Tableau formula to translate
      "datatype": "...",           // original data type
      "owner_table": "...",        // pre-assigned Power BI table
      "target_dax_approach": "...", // recommended translation strategy
      "translatability": "full|partial|manual",
      "dependencies": [...]        // other measures this depends on
    }
  ]
}
```

A mandatory "Available Power BI Tables" header lists exact table names from the TDD semantic model design. Use ONLY these names for table references.

### What to extract

#### From `datasources[*].calculated_fields[]`

Each entry has:
| Field | Description |
|---|---|
| `name` | Internal Tableau name, e.g. `[Calculation_0831103...]` |
| `caption` | Human-readable display name — **use this as the DAX measure name** |
| `datatype` | `integer`, `real`, `string`, `boolean`, `date` |
| `role` | `measure` or `dimension` |
| `formula` | Tableau formula to translate to DAX |
| `hidden` | If `true`, note it with `isHidden = true` in TMDL |

**Name resolution rule:** If `caption` is non-null, use it as the measure name. If `caption` is null, strip the brackets from `name` (e.g. `[Compenso totale]` → `Compenso totale`).

#### From `datasources[*].columns[]`

These are physical/logical columns — they become **table columns**, not measures. You do not need to emit TMDL for them unless they are used by calculated fields.

#### From `parameters[]`

Each entry has:
| Field | Description |
|---|---|
| `name` | Internal name, e.g. `[Nuova quota]` |
| `caption` | Display name |
| `datatype` | Data type |
| `default_value` | The default scalar value |
| `domain_type` | `range` or `list` |
| `range` / `allowed_values` | Constraints |

Tableau parameters become **DAX measures** that return their default value, placed in
a dedicated `Parameters` table.

---

## Step 2 — Translate Tableau Formulas to DAX

Apply these translation rules systematically.

### 2.1 Aggregation Functions

| Tableau | DAX |
|---|---|
| `SUM([Field])` | `SUM('Table'[Field])` |
| `AVG([Field])` | `AVERAGE('Table'[Field])` |
| `MIN([Field])` | `MIN('Table'[Field])` |
| `MAX([Field])` | `MAX('Table'[Field])` |
| `COUNT([Field])` | `COUNT('Table'[Field])` |
| `COUNTD([Field])` | `DISTINCTCOUNT('Table'[Field])` |
| `MEDIAN([Field])` | `MEDIAN('Table'[Field])` |

### 2.2 Conditional Logic

| Tableau | DAX |
|---|---|
| `IF <cond> THEN <a> ELSEIF <b> THEN <c> ELSE <d> END` | `IF(<cond>, <a>, IF(<b>, <c>, <d>))` |
| `IIF(<cond>, <true>, <false>)` | `IF(<cond>, <true>, <false>)` |
| `CASE [Field] WHEN "x" THEN 1 WHEN "y" THEN 2 ELSE 0 END` | `SWITCH('Table'[Field], "x", 1, "y", 2, 0)` |

### 2.3 Date Functions

| Tableau | DAX |
|---|---|
| `DATEDIFF('day', [Start], [End])` | `DATEDIFF('Table'[Start], 'Table'[End], DAY)` |
| `DATEDIFF('month', ...)` | `DATEDIFF(..., MONTH)` |
| `DATEDIFF('year', ...)` | `DATEDIFF(..., YEAR)` |
| `DATEPART('year', [Date])` | `YEAR('Table'[Date])` |
| `DATEPART('month', [Date])` | `MONTH('Table'[Date])` |
| `DATEPART('day', [Date])` | `DAY('Table'[Date])` |
| `DATEADD('month', n, [Date])` | `EDATE('Table'[Date], n)` |
| `TODAY()` | `TODAY()` |
| `NOW()` | `NOW()` |

### 2.4 String Functions

| Tableau | DAX |
|---|---|
| `STR([Field])` | `FORMAT('Table'[Field], "General")` |
| `LEN([Field])` | `LEN('Table'[Field])` |
| `CONTAINS([Field], "x")` | `CONTAINSSTRING('Table'[Field], "x")` |
| `LEFT([Field], n)` | `LEFT('Table'[Field], n)` |
| `RIGHT([Field], n)` | `RIGHT('Table'[Field], n)` |
| `MID([Field], s, n)` | `MID('Table'[Field], s, n)` |
| `TRIM([Field])` | `TRIM('Table'[Field])` |
| `UPPER([Field])` | `UPPER('Table'[Field])` |
| `LOWER([Field])` | `LOWER('Table'[Field])` |

### 2.5 Math Functions

| Tableau | DAX |
|---|---|
| `ROUND([Field], n)` | `ROUND([Field], n)` |
| `ABS([Field])` | `ABS([Field])` |
| `SQRT([Field])` | `SQRT([Field])` |
| `POWER([Field], n)` | `POWER([Field], n)` |
| `ZN([Field])` | `IF(ISBLANK([Field]), 0, [Field])` |
| `ISNULL([Field])` | `ISBLANK([Field])` |

### 2.6 LOD (Level of Detail) Expressions

Tableau LOD expressions are the most complex to migrate. Use `CALCULATE` + `ALL`/`ALLEXCEPT`:

| Tableau | DAX |
|---|---|
| `{FIXED [Dim] : SUM([Measure])}` | `CALCULATE(SUM('Table'[Measure]), ALLEXCEPT('Table', 'Table'[Dim]))` |
| `{INCLUDE [Dim] : SUM([Measure])}` | Use a related table or `SUMMARIZE` with `ADDCOLUMNS` |
| `{EXCLUDE [Dim] : SUM([Measure])}` | `CALCULATE(SUM('Table'[Measure]), ALL('Table'[Dim]))` |

### 2.7 Table Calculations (⚠ Not directly translatable)

The following Tableau functions do **not** have a direct DAX equivalent and require manual redesign:

| Tableau | DAX Approach |
|---|---|
| `INDEX()` | `RANKX` or `ROW_NUMBER` pattern using `ADDCOLUMNS` + `RANKX` |
| `RANK()` | `RANKX(ALL('Table'), [Measure])` |
| `WINDOW_SUM(...)` | Running total via `CALCULATE(..., FILTER(ALL(...), ...))` |
| `RUNNING_SUM([M])` | `CALCULATE(SUM([M]), FILTER(ALLSELECTED(...), [Date] <= MAX([Date])))` |
| `LOOKUP(...)` | Time intelligence or offset patterns |

Flag these in the `_warnings` array in the JSON output — do NOT add any annotation on the measure itself in TMDL.

### 2.8 Parameter References

Tableau: `[Parameters].[Nuova quota]`
DAX: `[Nuova quota]` (referencing the parameter measure defined in the Parameters table)

Strip the `[Parameters].` prefix and treat the result as a measure reference.

### 2.9 Cross-Datasource References

Tableau: `[federated.0hgpf0j1fdpvv316shikk0mmdlec].[Obiettivo di vendita]`
DAX: Reference the corresponding table directly: `SUM('Obiettivo di vendita'[Obiettivo di vendita])`

Map the federation ID to the datasource's `caption` field to identify the correct table name.

### 2.10 Field Reference Normalization

- Strip brackets: `[Field Name]` → `'Table'[Field Name]`
- If a field is a **calculated measure** (defined in `calculated_fields`), reference it as `[Measure Name]` (no table prefix)
- If a field is a **physical column** (defined in `columns` or `tables[*].columns`), reference it as `'TableName'[Column Name]`

---

## Step 3 — Determine the Table Name for Each Measure

**CRITICAL — use the table names provided in the prompt, not Tableau captions.**

If the prompt contains a section titled `## Available Power BI Tables (MANDATORY)`,
you MUST use those exact names for all table and column references in DAX.  The
semantic model agent may rename or split Tableau datasources — for example a single
datasource `Esempio - Supermercato` may be split into `Ordini`, `Persone`, `Resi`,
etc., one table per Excel sheet.  Using the original Tableau caption as the table
name creates a table that has no data source, which breaks the Power BI model.

**Mapping rules when the table list is provided:**

1. For each calculated field, find which provided table holds its physical columns
   (use the column names in the Tableau metadata as a guide).
2. Use that table name — not the Tableau datasource caption — in all DAX column
   references: `'ActualTableName'[ColumnName]`.
3. If a measure does not reference any physical column (e.g. it only calls other
   measures or returns a constant), place it in whichever table is its logical home,
   or in the `Parameters` table if it originates from a Tableau parameter.
4. Never emit a `table` block for a name that is NOT in the provided list (except
   the dedicated `Parameters` table for Tableau parameters).

**Fallback (no table list provided):** use the datasource `caption` field as the
table name. This is the legacy behaviour for workbooks processed without the
semantic model output available.

---

## Step 4 — Write the TMDL Files

### CRITICAL — PBIP TMDL Structure

In a Power BI Project (PBIP), the semantic model uses **individual `.tmdl` files**
placed under the `<WorkbookName>.SemanticModel/definition/` folder.

**Each table gets its own `.tmdl` file.** Table files must NOT contain `database` or
`model` wrappers — those are separate files at the `definition/` level.

### File Layout

```
<WorkbookName>.SemanticModel/
    definition/
        database.tmdl
        model.tmdl
        tables/
            <TableName>.tmdl    ← one per datasource table
            Parameters.tmdl     ← dedicated table for Tableau parameters
```

### CRITICAL — Line 1 must be a valid TMDL declaration

The TMDL parser rejects any file whose first line is not a recognized TMDL declaration.
This means:
- **NEVER start a `.tmdl` file with a `//` comment**
- **NEVER start a `.tmdl` file with a blank line**
- The very first line must be a keyword like `table`, `model`, or `compatibilityLevel`

Any migration notes or warnings must go in the `_warnings` array in the JSON output.
**NEVER add `description` properties to measures in TMDL — they cause the model to fail to load.**

### `database.tmdl`

```tmdl
compatibilityLevel: 1567
```

One line only. No comments, no blank lines before it.

### `model.tmdl`

```tmdl
model Model
	culture: it-IT
	defaultPowerBIDataSourceVersion: powerBI_V3
```

First line is `model Model`. Properties indented with one tab.

### Per-Table `.tmdl` File Structure

Each table file starts with `table 'TableName'` on line 1:

```tmdl
table 'Esempio - Supermercato'

	measure 'Rapporto profitto' = DIVIDE(SUM('Esempio - Supermercato'[Profitto]), SUM('Esempio - Supermercato'[Vendite]))
		formatString: 0.00%

	measure 'Vendite per cliente' = DIVIDE(SUM('Esempio - Supermercato'[Vendite]), DISTINCTCOUNT('Esempio - Supermercato'[Nome cliente]))
		formatString: 0.00
```

### TMDL Indentation Rules

TMDL uses **tab characters** for indentation (NOT spaces). The hierarchy is:

```
table 'Name'              ← column 0, no indentation
                           ← blank line separating table declaration from measures
[TAB]measure 'X' = ...   ← 1 tab
[TAB][TAB]formatString: . ← 2 tabs
[TAB][TAB]isHidden: true  ← 2 tabs
[TAB][TAB]description: .. ← 2 tabs
                           ← blank line between measures
[TAB]measure 'Y' = ...   ← 1 tab
```

### Multi-line DAX Expressions

For complex DAX that spans multiple lines, use TMDL line continuation.
Each continuation line is indented with **3 tabs** (measure body level):

```tmdl
	measure 'Stato spedizione' =
			var __actual = [Giorni per spedizione effettivi]
			var __planned = [Giorni per spedizione pianificati]
			return
			IF(__actual > __planned, "In ritardo", IF(__actual = __planned, "Puntuale", "In anticipo"))
		formatString: 0
```

### Warning Annotations on Measures

**NEVER add `description`, `// comment`, or any extra properties to measures in TMDL.**
These cause the semantic model to fail to load. All warnings and annotations must go
exclusively in the `_warnings` array in the JSON output.

```tmdl
	measure 'Classifica sopra 3' = BLANK()
```

Then in the JSON `_warnings` array:
```json
{"severity": "WARN", "code": "TABLE_CALC", "message": "Measure 'Classifica sopra 3' uses INDEX() — no direct DAX equivalent. Requires manual review."}
```

### Parameter Measures

Parameters go in a dedicated `Parameters` table:

```tmdl
table Parameters

	measure 'Nuova quota' = 500000
		formatString: 0

	measure 'Stipendio base' = 50000
		formatString: 0
```

Parameter origin notes go in the `_warnings` array, NOT as `description` properties.

### Data Type → Format String Mapping

| Tableau datatype | TMDL formatString |
|---|---|
| `integer` | `0` |
| `real` | `0.00` |
| `string` | *(omit formatString)* |
| `boolean` | *(omit formatString)* |
| `date` | `Short Date` |
| `percent` (inferred from formula like `x/y` ratio) | `0.00%` |

---

## Step 5 — Handle Edge Cases

### Circular References
If measure A references measure B and measure B references measure A, flag both
in the `_warnings` array — do NOT add any `description` or comment to the TMDL measure.

### Null / Division by Zero
Replace raw division `A / B` with `DIVIDE(A, B)` to safely handle division by zero.

### Comments in Formulas
Tableau supports `// comment` inline. Strip these from DAX output (DAX measures in TMDL
do not support inline comments within the expression body).

### `\r\n` in Formulas
The JSON may encode multi-line Tableau formulas with `\r\n`. Normalize to single-line
or proper TMDL multi-line continuation format.

### Hidden Measures
Set `isHidden: true` in TMDL for fields where `"hidden": true` in the JSON.

### Measures Referencing Other Calculated Fields
When a formula references another calculated field by its internal name
(e.g. `[Calculation_0831103151444568]`), resolve it to the human-readable caption
before emitting DAX:
- Build a lookup map: `{ "[Calculation_0831103151444568]": "Giorni per spedizione effettivi", ... }`
- Replace all internal `[Calculation_XXXXXXX]` references with their resolved captions

---

## Step 6 — Power BI DAX Correctness Rules (apply at generation time)

These rules must be applied while writing every measure. They mirror the validator agent's
rule catalogue — following them here reduces the number of fixes needed downstream.

### R01 — Never use bare column references inside a measure body

A measure executes in a filter context. A bare `'Table'[Column]` reference without an
aggregation wrapper is illegal and will prevent the model from loading.

**Rule:** Every column reference inside a measure must be wrapped in an aggregation
(`SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `DISTINCTCOUNT`) OR in `SELECTEDVALUE()` for
dimension/string columns — UNLESS it appears as the direct argument of one of those
aggregation functions itself.

**Most common trigger — `DATEDIFF`:** Always wrap both date column arguments with `MAX()`:
```
WRONG:  DATEDIFF('T'[Data ordine], 'T'[Data spedizione], DAY)
RIGHT:  DATEDIFF(MAX('T'[Data ordine]), MAX('T'[Data spedizione]), DAY)
```

### R02 — Never return a raw boolean from a measure

A measure whose top-level expression ends with a comparison operator (`>`, `<`, `>=`, `<=`,
`=`, `<>`) returns a boolean type, which Power BI rejects.

**Rule:** Always wrap boolean-returning expressions in `IF(..., TRUE(), FALSE())` or return
a string/integer instead.
```
WRONG:  = CALCULATE(SUM('T'[Profitto]), ALLEXCEPT('T', 'T'[ID])) > 0
RIGHT:  = IF(CALCULATE(SUM('T'[Profitto]), ALLEXCEPT('T', 'T'[ID])) > 0, TRUE(), FALSE())
```

### R03 — Escape apostrophes in measure names

TMDL delimits measure names with single quotes. A literal `'` inside the name terminates
the string early.

**Rule:** Any apostrophe inside a measure name must be doubled (`''`).
```
WRONG:  measure 'Vendite superiori all'obiettivo?' = ...
RIGHT:  measure 'Vendite superiori all''obiettivo?' = ...
```

### R04 — Always provide a default for SELECTEDVALUE

`SELECTEDVALUE('T'[Col])` with no second argument returns BLANK when multiple rows are
selected, silently breaking downstream calculations.

**Rule:** Always write `SELECTEDVALUE('T'[Col], <default>)`. Use the last/else branch of
the enclosing `SWITCH` or `IF` as the default.
```
WRONG:  SWITCH(SELECTEDVALUE('T'[Modalità spedizione]), "Veloce", 1, ..., 6)
RIGHT:  SWITCH(SELECTEDVALUE('T'[Modalità spedizione], "Standard"), "Veloce", 1, ..., 6)
```

### R05 — Do not emit MIN(x, x) or MAX(x, x) with identical arguments

When translating Tableau's `MIN([measure])` (single-argument, scalar), do NOT emit
`MIN([measure], [measure])` (two-argument DAX form). The two-arg form is a no-op and
signals a translation error.

**Rule:** Tableau `MIN([M])` where `[M]` is a measure → emit `[M]` directly.
```
WRONG:  = MIN([Base (Variabile)], [Base (Variabile)]) + [Commissione (Variabile)]
RIGHT:  = [Base (Variabile)] + [Commissione (Variabile)]
```

### R06 — Flag untranslatable table calculations explicitly

Tableau table calculations (`INDEX()`, `RANK()`, `WINDOW_SUM()`, `RUNNING_SUM()`,
`LOOKUP()`) have no direct DAX equivalent.

**Rule:** Do NOT emit `BLANK()` silently. Emit a `BLANK()` placeholder AND include a
`_warnings` entry for this measure in the JSON response. Do NOT add `description` or
any other extra properties to the measure in TMDL.

### R07 — Use DIVIDE() instead of raw division

Raw `/` raises a divide-by-zero error in Power BI. `DIVIDE()` returns BLANK safely.

**Rule:** Never emit `A / B`. Always emit `DIVIDE(A, B)`.

---

## Step 7 — Output Format

Produce a **flat JSON object** where each key is a relative file path and each value
is the file content as a string. Use `\n` for newlines and `\t` for tabs within
string values.

**CRITICAL — Output compactness:** To avoid token-limit truncation, produce compact
single-line JSON with no indentation in the outer envelope.

### Required files

1. `<WorkbookName>.SemanticModel/definition/database.tmdl`
2. `<WorkbookName>.SemanticModel/definition/model.tmdl`
3. `<WorkbookName>.SemanticModel/definition/tables/<TableName>.tmdl` — one per datasource
4. `<WorkbookName>.SemanticModel/definition/tables/Parameters.tmdl` — for Tableau parameters
5. `_warnings` — array of warning objects

### Example output

```json
{"Supermercato.SemanticModel/definition/database.tmdl":"compatibilityLevel: 1567\n","Supermercato.SemanticModel/definition/model.tmdl":"model Model\n\tculture: it-IT\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n","Supermercato.SemanticModel/definition/tables/Esempio - Supermercato.tmdl":"table 'Esempio - Supermercato'\n\n\tmeasure 'Rapporto profitto' = DIVIDE(SUM('Esempio - Supermercato'[Profitto]), SUM('Esempio - Supermercato'[Vendite]))\n\t\tformatString: 0.00%\n","Supermercato.SemanticModel/definition/tables/Parameters.tmdl":"table Parameters\n\n\tmeasure 'Nuova quota' = 500000\n\t\tformatString: 0\n","_warnings":[{"severity":"WARN","code":"TABLE_CALC","message":"Measure 'Classifica sopra 3' uses INDEX()"},{"severity":"INFO","code":"TABLEAU_PARAMETER","message":"Measure 'Nuova quota' is a Tableau parameter with default value 500000"}]}
```

### Key rules:

1. **Line 1 of every `.tmdl` file MUST be a valid TMDL declaration** — NEVER a comment, NEVER a blank line
2. **Use `\t` (literal tab) for indentation** — NOT spaces
3. **Use `\n` for line breaks** inside string values
4. **One `.tmdl` file per table** under `tables/`
5. **Parameters go in a dedicated `Parameters` table**
6. **No `database` or `model` wrapper inside table files**
7. **`database.tmdl` and `model.tmdl` are separate files** at the `definition/` level
8. **The entire output is a single line of valid JSON** — no pretty-printing
9. **No markdown fences** in output

---

## Complete Field Translation Reference (from this workbook)

The following fields appear in the attached JSON and their expected DAX translations:

### Datasource: Commissione vendite

| Tableau Caption | Formula | DAX Translation |
|---|---|---|
| Base (Variabile) | `[Parameters].[Stipendio base]` | `[Stipendio base]` |
| % di quota raggiunta | `AVG([Obiettivo (copy)])/[Parameters].[Nuova quota]` | `DIVIDE(AVERAGE('Commissione vendite'[Obiettivo (stimato)]), [Nuova quota])` |
| Classifica sopra 3 | `ROUND(INDEX() / 3 - 0.6, 0) + 1` | `BLANK()` with description: `⚠ TABLE CALC — INDEX has no direct DAX equivalent` |
| Ordina per campo | IF on parameter string | `SWITCH(TRUE(), [Ordina per] = "Nomi", 0, [Ordina per] = "% quota decrescente", -[% di quota raggiunta], [% di quota raggiunta])` |
| Commissione (Variabile) | `([Parameters].[Tasso di commissione]*[Vendite])/100` | `DIVIDE([Tasso di commissione] * SUM('Commissione vendite'[Vendite]), 100)` |
| Compenso totale | `MIN([Base (Variabile)]) + SUM([Commissione (Variabile)])` | `[Base (Variabile)] + [Commissione (Variabile)]` |
| OTE (Variabile) | `[Stipendio base] + ([Tasso di commissione]*[Nuova quota])/100` | `[Stipendio base] + DIVIDE([Tasso di commissione] * [Nuova quota], 100)` |
| Quota raggiunta | Nested IF on SUM thresholds | Multi-branch `IF(...)` in DAX |

### Datasource: Esempio - Supermercato

| Tableau Caption | Formula | DAX Translation |
|---|---|---|
| Giorni per spedizione effettivi | `DATEDIFF('day',[Data ordine],[Data spedizione])` | `DATEDIFF(MAX('Esempio - Supermercato'[Data ordine]), MAX('Esempio - Supermercato'[Data spedizione]), DAY)` |
| Previsione di vendita | `[Vendite]*(1-[Parameter 2])*(1+[Parameter 1])` | `SUM('Esempio - Supermercato'[Vendite]) * (1 - [Tasso di abbandono]) * (1 + [Crescita nuove attività])` |
| Stato spedizione | IF comparing two calc fields | `IF([Giorni per spedizione effettivi] > [Giorni per spedizione pianificati], "Spedizione in ritardo", IF([Giorni per spedizione effettivi] = [Giorni per spedizione pianificati], "Spedizione puntuale", "Spedizione in anticipo"))` |
| Giorni per spedizione pianificati | CASE on [Modalità spedizione] | `SWITCH(SELECTEDVALUE('Esempio - Supermercato'[Modalità spedizione], "Standard"), "Stesso giorno", 0, "Veloce", 1, "Due/tre giorni", 3, "Standard", 6)` |
| Ordine redditizio? | `{fixed [ID ordine]:sum([Profitto])}>0` | `IF(CALCULATE(SUM('Esempio - Supermercato'[Profitto]), ALLEXCEPT('Esempio - Supermercato', 'Esempio - Supermercato'[ID ordine])) > 0, TRUE(), FALSE())` |
| Vendite per cliente | `Sum([Vendite])/countD([Nome cliente])` | `DIVIDE(SUM('Esempio - Supermercato'[Vendite]), DISTINCTCOUNT('Esempio - Supermercato'[Nome cliente]))` |
| Rapporto profitto | `sum([Profitto])/sum([Vendite])` | `DIVIDE(SUM('Esempio - Supermercato'[Profitto]), SUM('Esempio - Supermercato'[Vendite]))` |
| Vendite superiori all'obiettivo? | IF comparing sales vs target cross-datasource | `IF(SUM('Esempio - Supermercato'[Vendite]) > SUM('Obiettivo di vendita'[Obiettivo di vendita]), "Superiore all''obiettivo", "Inferiore all''obiettivo")` |
| Profitto per ordine | `Sum([Profitto])/countD([ID ordine])` | `DIVIDE(SUM('Esempio - Supermercato'[Profitto]), DISTINCTCOUNT('Esempio - Supermercato'[ID ordine]))` |

### Parameters (emit as measures in a dedicated `Parameters` table)

| Caption | Default Value | DAX |
|---|---|---|
| Nuova quota | 500000 | `500000` |
| Ordina per | "Nomi" | `"Nomi"` |
| Crescita nuove attività | 0.6 | `0.6` |
| Tasso di abbandono | 0.064 | `0.064` |
| Stipendio base | 50000 | `50000` |
| Tasso di commissione | 18.4 | `18.4` |

---

## Checklist Before Finalizing Output

- [ ] Every `.tmdl` file starts with a valid TMDL declaration on line 1 (NO comments, NO blank lines before it)
- [ ] Indentation uses tab characters (`\t`), NOT spaces
- [ ] No `database` or `model` wrapper inside table `.tmdl` files
- [ ] `database.tmdl` exists with just `compatibilityLevel: 1567` on line 1
- [ ] `model.tmdl` exists with `model Model` on line 1 and properties indented with tabs
- [ ] One `.tmdl` file per datasource table + one `Parameters.tmdl`
- [ ] All `[Calculation_XXXXXXXXX]` internal names resolved to captions
- [ ] All `[Parameters].[X]` references resolved to plain measure references
- [ ] All cross-datasource federation IDs resolved to table captions
- [ ] `DIVIDE()` used wherever raw `/` division appears
- [ ] **NO `description` properties on any measure** — they break the model
- [ ] **NO `//` comments anywhere in TMDL files** — all annotations go in `_warnings` JSON array
- [ ] Table calculations flagged in `_warnings` array (never in TMDL file content)
- [ ] Parameters noted in `_warnings` array (never as `description` on the measure)
- [ ] LOD expressions translated to `CALCULATE` + `ALLEXCEPT/ALL`
- [ ] Boolean-returning measures wrapped in `IF(..., TRUE(), FALSE())`
- [ ] Bare column references wrapped in aggregation functions
- [ ] Apostrophes in measure names doubled (`''`)
- [ ] `SELECTEDVALUE` calls include a default second argument
- [ ] Inline Tableau comments stripped from DAX
- [ ] `hidden: true` fields have `isHidden: true` in TMDL (this is allowed — it's a standard TMDL property)
- [ ] Parameters emitted in a dedicated `Parameters` table with `description` annotations
- [ ] The entire output is valid JSON parseable by `json.loads()`
- [ ] Output is compact single-line JSON — no pretty-printing
- [ ] No markdown fences in output