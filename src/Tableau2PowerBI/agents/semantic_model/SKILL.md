---
name: pbip_semantic_model_generator_agent
---

# PBIP Semantic Model Decision Generator

Analyze the Target Technical Design (TDD) document and return **structured decisions** for building a Power BI semantic model. The TDD contains a `semantic_model_design` section with pre-analysed table definitions, column mappings, M query strategies, relationships, and parameters — plus a slim DAX measures summary for cross-reference. Return decisions only — the caller handles all file formatting, indentation, quoting, UUID generation, and file templates.

## Output Format

Return **only** raw JSON (no markdown, no code fences, no prose) matching this structure:

```json
{
  "tables": [...],
  "relationships": [...],
  "parameters": [...],
  "warnings": [...],
  "source_query_culture": "it-IT"
}
```

### `source_query_culture`

BCP-47 locale tag for the semantic model. Infer from workbook content: Italian column names → `it-IT`, German → `de-DE`, French → `fr-FR`, etc. Default `en-US` if ambiguous.

### Table

```json
{
  "name": "table declaration/filename name",
  "query_group": "Fact",
  "columns": [...],
  "m_query": "let\n    Source = ...\nin\n    Source",
  "is_calc_group": false,
  "calc_items": []
}
```

- **`name`**: use the pre-computed `pbi_table_name` provided in the prompt's "Pre-computed Table Names" section. These names are deterministically assigned by the pipeline and **MUST be used exactly as given**. Do NOT invent, rename, translate, prefix, or modify table names. The `pbi_table_name` is both the TMDL declaration name and the `.tmdl` filename.
- **`query_group`**: `"Dimension"` for lookup/reference tables; `"Fact"` for all others.
- **`columns`**: list of column decisions (see below). Exclude internal fields (`[:…]`). Deduplicate by `source_column` — emit only the first occurrence.
- **`m_query`**: complete Power Query M expression including `let`/`in` wrapper. See M Query rules below.
- **`is_calc_group`**: `true` if the datasource has a `calculationGroup`. When true, `columns` and `m_query` are ignored — the assembler generates standard calc group columns.
- **`calc_items`**: calculation item names (only when `is_calc_group` is true).

**ONE table per datasource table entry.** When a datasource has multiple `tables` entries (e.g. multi-sheet Excel), emit one PBI table for **each** entry in `tables[]`. Never combine multiple sheets into one table.

### Column

```json
{
  "name": "column display name",
  "source_column": "physical source column name (remote_name)",
  "data_type": "string",
  "summarize_by": "none"
}
```

- **`name`**: use `caption` if available, else strip brackets from the logical `name` field.
- **`source_column`**: the `remote_name` from `physical_columns`. This is the raw physical column name — never quoted.
- **`data_type`**: map from Tableau types:

| Tableau type | `data_type` value |
|---|---|
| string | `string` |
| integer | `int64` |
| real | `double` |
| boolean | `boolean` |
| date / datetime | `dateTime` |

- **`summarize_by`**: `"none"` for `dimension` role; `"sum"` for `measure` role. Override to `"none"` if the column is `int64` and the name contains `id`/`key`/`year`/`code` (case-insensitive) — and emit `WARN_SUMMARIZE_ID`.

### Relationship

```json
{
  "from_table": "FactTableName",
  "from_column": "FKColumnName",
  "to_table": "DimTableName",
  "to_column": "PKColumnName",
  "is_active": true
}
```

- Generate only when the FK is **deterministically inferable** from `relationships` + `col_mapping`.
- Use `col_mapping` to resolve logical field names → physical `remote_name` values.
- Relationships must connect **two different tables**. Never emit self-referencing relationships within the same table.
- If uninferable → omit from the list and emit `WARN_AMBIGUOUS_REL` with candidate columns.

#### Ambiguous paths — `is_active`

Power BI forbids two **active** relationship paths between the same pair of tables. Before emitting relationships, check for ambiguous paths: if table A can reach table C both directly (A→C) and indirectly (A→B→C), one of the paths must be marked `"is_active": false`. The **direct** relationship is usually the one to deactivate because the indirect path through the shared dimension is more generally useful in the star schema. Use your judgement based on the data model semantics — the goal is exactly **one active path** between every pair of tables. DAX measures can still use inactive relationships via `USERELATIONSHIP()`.

Default is `true` — omit the field or set `true` when there is no ambiguity.

### Parameter

```json
{
  "name": "parameter display name",
  "pbi_type": "Number",
  "default_value": "500000"
}
```

- **`name`**: use `caption` for the display name. Never include Tableau brackets `[...]`.
- **`pbi_type`**: map from Tableau: `string` → `Text`, `integer`/`real` → `Number`, `date` → `Date`, `datetime` → `DateTime`, `boolean` → `Logical`.
- **`default_value`**: the M literal expression. Strings must include M quotes: `"Nomi"`. Numbers are bare: `500000`. No parameters → empty array `[]`.

### Warning

```json
{
  "code": "WARN_NO_DATASOURCE",
  "severity": "warning",
  "message": "description",
  "source_path": "optional/path",
  "manual_review_required": true
}
```

| Code | Trigger |
|---|---|
| `WARN_SET` | Tableau set construct |
| `WARN_BIN` | Tableau bin field |
| `WARN_NO_DATASOURCE` | Missing/incomplete connection metadata |
| `WARN_AMBIGUOUS_REL` | Uninferable relationship — list candidate join columns |
| `WARN_DATE_TYPE_MISMATCH` | String column transformed to dateTime |
| `WARN_SUMMARIZE_ID` | Integer column with id/key/year/code → summarizeBy: none |
| `WARN_UNRESOLVED_PATH` | File-based connection with no `relative_path` — path may not work on the target machine |
| `WARN_HYPER_EXTRACT` | Tableau Hyper/TDE extract — no direct PBI equivalent; manual data source reconfiguration needed |
| `WARN_UNSUPPORTED_CONNECTOR` | Connection type not natively supported by Power BI — manual reconfiguration needed |

## M Query Rules

### Source of truth

Build `m_query` **exclusively** from the datasource's `connection` and `tables[]` metadata. Never invent file paths, sheet names, or connection details.

### File path resolution

For file-based connections (`excel-direct`, `textscan`, etc.), the connection may contain:
- `connection.relative_path` — **relative path** from the PBIP project root to the data file. **Always use this** when present. The assembler places data files at this exact relative location next to the `.pbip` file.
- `connection.filename` — the original path from the Tableau workbook. Fallback only when `relative_path` is absent.

**Rule**: Use `relative_path` if it exists. Fall back to `filename` only when `relative_path` is absent — and emit `WARN_UNRESOLVED_PATH` in that case. Ignore `resolved_filename` (it is an internal implementation detail).

**Do NOT parameterize file paths** — the assembler automatically wraps every `File.Contents("...")` call with a `DataFolderPath` parameter reference so the user can set the absolute base path once in Power BI. Just use the plain relative path inside `File.Contents("...")`.

### How to read the metadata

Each datasource provides:
- `connection` — a dict of ALL connection attributes from the Tableau XML. Key fields vary by connection type. Common ones include:
  - `connection.type` — the connection type identifier (e.g. `excel-direct`, `textscan`, `sqlserver`, `vertica`, `databricks`, `snowflake`, `bigquery`, `oracle`, `postgres`, `mysql`, `sap_hana`, `dataengine`, etc.)
  - `connection.filename` — file path (for file-based sources)
  - `connection.relative_path` — resolved relative path from PBIP root (preferred, when present)
  - `connection.server` — server/host name (for database sources)
  - `connection.database` — database name
  - `connection.schema` — schema name
  - `connection.port` — port number
  - `connection.warehouse` — warehouse (Snowflake, Databricks)
  - `connection.httpPath` — HTTP path (Databricks)
  - `connection.catalog` — catalog name (Databricks Unity Catalog)
  - `connection.service` — service name (Oracle)
  - `connection.authentication` — authentication method
  - `connection.sslmode` — SSL mode
  - …and potentially other attributes specific to the connection type
- `tables[]` — array of physical tables within this datasource
  - `tables[].name` — **the sheet/table name** to use in M navigation (e.g. `"Ordini"`, `"Sheet1"`)
  - `tables[].physical_table` — Tableau's internal reference (e.g. `[Ordini$]`) — **do NOT use this value in M expressions**

### Generating M Queries for ANY Connection Type

You must generate valid Power Query M expressions for **any** Tableau connection type. Use the connection metadata to determine the appropriate Power Query connector function. Here are the principles and examples:

#### General principles

1. **Use the standard Power Query connector** that matches the source system. If you know the correct PQ function, use it. If the connection type is unfamiliar, use the closest available Power Query connector and emit `WARN_UNSUPPORTED_CONNECTOR`.
2. **Extract connection parameters from the metadata** — server, database, schema, port, warehouse, etc. are all available in the `connection` dict.
3. **Navigate to the specific table** using the table name from `tables[].name`.
4. **Always use `let`/`in` syntax**.

#### Common connection types and their Power Query patterns

**Excel files** (`excel-direct`):
```
let
    Source = Excel.Workbook(File.Contents("<relative_path>"), true, true),
    Data = Source{[Name="<tables[].name>"]}[Data]
in
    Data
```
- Use `{[Name="..."]}` navigation (works for both .xls and .xlsx). Do **NOT** use `{[Item=...,Kind="Sheet"]}` — it fails on `.xls` files.
- When multiple `tables[]` entries exist, emit **one PBI table per entry**, each navigating to its own sheet.

**CSV/text files** (`textscan`):
```
let
    Source = Csv.Document(File.Contents("<relative_path>"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true])
in
    PromotedHeaders
```
- Use `QuoteStyle.Csv` (RFC 4180) so quoted fields containing commas, e.g. `"74,814"`, are parsed as a single value. **Never** use `QuoteStyle.None` — it treats commas inside quotes as field delimiters.

**SQL Server** (`sqlserver`, `sqlproxy`):
```
let
    Source = Sql.Database("<server>", "<database>"),
    Data = Source{[Schema="<schema>", Item="<table>"]}[Data]
in
    Data
```

**PostgreSQL** (`postgres`):
```
let
    Source = PostgreSQL.Database("<server>:<port>", "<database>"),
    Data = Source{[Schema="<schema>", Name="<table>"]}[Data]
in
    Data
```

**Oracle** (`oracle`):
```
let
    Source = Oracle.Database("<server>/<service>"),
    Data = Source{[Schema="<schema>", Name="<table>"]}[Data]
in
    Data
```

**MySQL** (`mysql`):
```
let
    Source = MySQL.Database("<server>:<port>", "<database>"),
    Data = Source{[Schema="<schema>", Name="<table>"]}[Data]
in
    Data
```

**Snowflake** (`snowflake`):
```
let
    Source = Snowflake.Databases("<server>", "<warehouse>"),
    DB = Source{[Name="<database>"]}[Data],
    Schema = DB{[Name="<schema>"]}[Data],
    Data = Schema{[Name="<table>"]}[Data]
in
    Data
```

**Databricks** (`databricks`):
```
let
    Source = Databricks.Catalogs("<server>", "<httpPath>"),
    Catalog = Source{[Name="<catalog>"]}[Data],
    Schema = Catalog{[Name="<schema>"]}[Data],
    Data = Schema{[Name="<table>"]}[Data]
in
    Data
```

**Google BigQuery** (`bigquery`):
```
let
    Source = GoogleBigQuery.Database([BillingProject="<project>"]),
    Dataset = Source{[Name="<dataset>"]}[Data],
    Data = Dataset{[Name="<table>"]}[Data]
in
    Data
```

**Vertica** (`vertica`):
```
let
    Source = Odbc.DataSource("Driver={Vertica};Server=<server>;Port=<port>;Database=<database>"),
    Data = Source{[Schema="<schema>", Name="<table>"]}[Data]
in
    Data
```

**SAP HANA** (`sap_hana`):
```
let
    Source = SapHana.Database("<server>:<port>"),
    Data = Source{[Schema="<schema>", Name="<table>"]}[Data]
in
    Data
```

**Amazon Redshift** (`redshift`):
```
let
    Source = AmazonRedshift.Database("<server>:<port>", "<database>"),
    Data = Source{[Schema="<schema>", Name="<table>"]}[Data]
in
    Data
```

#### Unfamiliar / unsupported connection types

If you encounter a connection type not listed above:
1. Examine all attributes in the `connection` dict
2. Identify the closest Power Query connector function
3. Build the best M query you can from available metadata
4. Emit `WARN_UNSUPPORTED_CONNECTOR` with details about the original Tableau connection type

#### Hyper / TDE extracts (`dataengine`)

Tableau Hyper extracts have no direct Power BI equivalent. If `connection.type` = `dataengine`:
1. Emit the table with a best-effort M query using `connection.relative_path` or `connection.filename`.
2. Always emit `WARN_HYPER_EXTRACT` warning.
3. **Never** emit `error "..."` or placeholder error stubs.

#### Other / incomplete connection

- Emit best-effort M query using whatever metadata is available.
- Add `WARN_NO_DATASOURCE` warning.
- **Never** emit `error "..."` or placeholder error stubs.

### M Syntax Reminders

- Each `let` step except the last needs a trailing comma.
- Row access on tables uses `{[...]}` not `[...]` (which is column access).
- The M expression must be syntactically valid Power Query M.

## Self-Check (run before returning)

1. Every table has at least one column (unless `is_calc_group`)
2. Every `data_type` is one of: `string`, `int64`, `double`, `boolean`, `dateTime`
3. Every `summarize_by` is one of: `none`, `sum`
4. Every `pbi_type` is one of: `Text`, `Number`, `Date`, `DateTime`, `Logical`
5. No placeholder error stubs in any `m_query`
6. No self-referencing relationships (same table on both sides)
7. `source_query_culture` is a valid BCP-47 tag
8. `warnings` key is always present (empty array if none)
9. Valid JSON output; no markdown/code fences/prose