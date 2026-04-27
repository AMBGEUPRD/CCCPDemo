"""Deterministic TMDL / PBIP file assembler.

Takes validated :class:`~.models.SemanticModelDecisions` and produces a
complete PBIP SemanticModel folder tree as ``dict[relative_path, content_string]``.

All TMDL formatting (TAB indentation, identifier quoting, property ordering,
UUID assignment) is handled here — **never by the LLM**.  The M query body
passes through a chain of deterministic post-processors that fix common
LLM mistakes:

1. :func:`_fix_m_let_commas` — missing commas between ``let`` steps
2. :func:`_fix_m_excel_navigation` — Item/Kind → Name-based sheet navigation
3. :func:`_fix_m_file_paths` — forward slashes → backslashes for Windows
4. :func:`_fix_m_csv_quote_style` — ``QuoteStyle.None`` → ``QuoteStyle.Csv``
5. :func:`_parameterize_file_paths` — replaces relative paths with DataFolderPath
6. :func:`_inject_column_types` — adds Table.TransformColumnTypes for type safety
"""

from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Tableau2PowerBI.agents.semantic_model.models import (
        SemanticModelDecisions,
        TableDecision,
    )

from Tableau2PowerBI.core.config import (
    SCHEMA_EDITOR,
    SCHEMA_LOCAL,
    SCHEMA_PBISM,
    SCHEMA_PLATFORM,
    TAB,
)


def _quote(name: str) -> str:
    """Single-quote a TMDL identifier, escaping internal ``'`` as ``''``."""
    return "'" + name.replace("'", "''") + "'"


def _uuid4() -> str:
    return str(uuid.uuid4())


# Matches the start of a new step assignment in a let...in block.
# E.g.: "Source = ...", "PromotedHeaders = ...", "Sheet1_Sheet = ..."
# Used by _fix_m_let_commas to detect where commas are needed.
_M_STEP_RE = re.compile(r"^[A-Za-z_]\w*\s*=")


def _fix_m_let_commas(m_text: str) -> str:
    """Ensure every ``let`` binding except the last has a trailing comma.

    LLMs sometimes omit the comma between consecutive ``let`` steps.
    Power BI's M engine rejects the expression with "Token ',' expected".
    This function patches the missing commas deterministically.
    """
    lines = m_text.split("\n")
    result: list[str] = []
    in_let = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped == "let":
            in_let = True
            result.append(line)
            continue

        # Detect the `in` keyword — must be alone or followed by whitespace.
        if in_let and (stripped == "in" or (stripped.startswith("in") and len(stripped) > 2 and stripped[2] in " \t")):
            in_let = False
            result.append(line)
            continue

        if in_let and stripped and not stripped.endswith(","):
            # Look ahead: is the next non-empty line a new step assignment?
            needs_comma = False
            for j in range(i + 1, len(lines)):
                next_stripped = lines[j].strip()
                if not next_stripped:
                    continue
                # Reached `in` keyword — this is the last step, no comma needed
                if next_stripped == "in" or (
                    next_stripped.startswith("in") and len(next_stripped) > 2 and next_stripped[2] in " \t"
                ):
                    break
                # Next non-empty line starts a new step → current line needs comma
                if _M_STEP_RE.match(next_stripped):
                    needs_comma = True
                break

            if needs_comma:
                result.append(line.rstrip() + ",")
                continue

        result.append(line)

    return "\n".join(result)


# The LLM sometimes generates {[Item="X",Kind="Sheet"]} navigation for Excel.
# This fails on .xls (legacy binary) files. {[Name="X"]} works universally.
_M_ITEM_KIND_RE = re.compile(r'\{[^}]*\[\s*Item\s*=\s*"([^"]+)"\s*,\s*Kind\s*=\s*"Sheet"\s*\]\s*\}')


def _fix_m_excel_navigation(m_text: str) -> str:
    """Rewrite ``Source{[Item="X",Kind="Sheet"]}`` → ``Source{[Name="X"]}``.

    The ``[Item=...,Kind="Sheet"]`` navigation pattern fails on ``.xls``
    (legacy binary Excel) files.  ``[Name="X"]`` works universally for
    both ``.xls`` and ``.xlsx`` with ``Excel.Workbook``.
    """
    return _M_ITEM_KIND_RE.sub(lambda m: '{[Name="' + m.group(1) + '"]}', m_text)


# Matches file paths inside File.Contents("...").
# Used by _fix_m_file_paths to normalise forward slashes to backslashes.
_M_FILE_CONTENTS_RE = re.compile(r'(File\.Contents\(")([^"]+)("\))')


def _fix_m_file_paths(m_text: str) -> str:
    r"""Normalise file paths inside ``File.Contents("...")`` for Windows.

    Power BI Desktop is Windows-only, so ``File.Contents()`` paths must use
    backslashes.  The LLM and the metadata pipeline may produce forward-slash
    paths (from zip archive entries or Unix-style normalisation).  This fixer
    rewrites them deterministically.

    .. note:: Platform assumption
       This assumes the PBIP output is consumed by Power BI Desktop on
       Windows.  If the project later targets Fabric direct-upload or
       cross-platform tooling, this normalisation should be revisited.
    """

    def _normalise(match: re.Match) -> str:
        prefix, path, suffix = match.group(1), match.group(2), match.group(3)
        normalised = path.replace("/", "\\")
        return f"{prefix}{normalised}{suffix}"

    return _M_FILE_CONTENTS_RE.sub(_normalise, m_text)


def _fix_m_csv_quote_style(m_text: str) -> str:
    """Replace ``QuoteStyle.None`` with ``QuoteStyle.Csv`` in ``Csv.Document`` calls.

    ``QuoteStyle.None`` treats all characters literally — commas inside
    double-quoted fields (e.g. ``"74,814"``) are parsed as column delimiters,
    producing mangled data with extra columns.  ``QuoteStyle.Csv`` follows
    RFC 4180 quoting rules and handles this correctly.  This post-processor
    applies the fix unconditionally because standard CSV quoting is the safe
    default for any data file.
    """
    if "Csv.Document" not in m_text:
        return m_text
    return m_text.replace("QuoteStyle.None", "QuoteStyle.Csv")


# Name of the auto-generated Power BI parameter for the project folder.
# All File.Contents() calls reference this so the user sets one path and
# every table resolves correctly.
_DATA_FOLDER_PARAM = "DataFolderPath"


def _parameterize_file_paths(m_text: str) -> str:
    """Replace relative paths in ``File.Contents("...")`` with a parameter reference.

    Power BI Desktop requires absolute paths in ``File.Contents()``.  Rather
    than embedding an absolute path that only works on one machine, we rewrite
    relative occurrences to ``File.Contents(DataFolderPath & "\\relative\\path")``.

    Absolute paths (drive-qualified like ``C:\\...`` or UNC paths like
    ``\\\\server\\share\\...``) are left unchanged because concatenating them
    with ``DataFolderPath`` would produce an invalid path.

    The companion ``DataFolderPath`` PBI parameter is emitted by the assembler
    in ``expressions.tmdl`` so the user only needs to set it once.
    """

    def _inject_param(match: re.Match) -> str:
        path = match.group(2)
        if re.match(r"^[A-Za-z]:[\\/]", path) or path.startswith("\\\\"):
            return match.group(0)
        # Prepend \ separator if the path doesn't already start with one,
        # so DataFolderPath & "\relative\path" concatenates correctly.
        if not path.startswith("\\"):
            path = "\\" + path
        # Build: File.Contents(DataFolderPath & "\relative\path")
        return f'File.Contents({_DATA_FOLDER_PARAM} & "{path}")'

    return _M_FILE_CONTENTS_RE.sub(_inject_param, m_text)


# Mapping from TMDL dataType values to Power Query M type expressions.
# Used by _inject_column_types to generate Table.TransformColumnTypes steps.
_TMDL_TO_M_TYPE: dict[str, str] = {
    "string": "type text",
    "int64": "Int64.Type",
    "double": "type number",
    "boolean": "type logical",
    "dateTime": "type datetime",
}


def _inject_column_types(m_text: str, columns: list) -> str:
    """Append a ``Table.TransformColumnTypes`` step to the M query.

    Without explicit type casting, file-based sources (Excel, CSV) return
    all columns as ``type any``.  Power BI's model layer then sees a
    mismatch between the declared TMDL column types and the actual M
    output types, causing "Table contains no data" warnings in Model View
    even though data loads successfully in Table View.

    This post-processor injects a final ``ChangedType`` step that casts
    every column to its declared TMDL type.  It is safe to run on any M
    query — if the query already contains ``Table.TransformColumnTypes``,
    it is left unchanged.
    """
    if not columns:
        return m_text
    if "Table.TransformColumnTypes" in m_text:
        return m_text  # already has explicit typing

    # Build the type assertion list: {"Col", type text}, {"Col2", Int64.Type}, ...
    type_pairs: list[str] = []
    for col in columns:
        m_type = _TMDL_TO_M_TYPE.get(col.data_type)
        if m_type is None:
            continue
        # Column source_column is the physical name that appears in the M output.
        type_pairs.append('{"' + col.source_column.replace('"', '""') + '", ' + m_type + "}")
    if not type_pairs:
        return m_text

    # Locate the let...in structure.
    lines = m_text.split("\n")
    in_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "in" or (stripped.startswith("in") and len(stripped) > 2 and stripped[2] in " \t"):
            in_idx = i
            break

    if in_idx is None:
        return m_text  # no let...in block

    # Detect indentation from the step before `in`.
    indent = ""
    for ch in lines[in_idx - 1]:
        if ch in " \t":
            indent += ch
        else:
            break

    # Ensure the last step before `in` has a trailing comma.
    last_step = lines[in_idx - 1].rstrip()
    if not last_step.endswith(","):
        lines[in_idx - 1] = last_step + ","

    # Determine what the `in` clause currently returns.
    in_line = lines[in_idx]
    in_parts = in_line.split(None, 1)  # ["in", "StepName"]
    if len(in_parts) >= 2:
        final_ref = in_parts[1].strip()
    elif in_idx + 1 < len(lines):
        final_ref = lines[in_idx + 1].strip()
    else:
        return m_text

    # Build the ChangedType step.
    # Always pass "en-US" culture so commas in CSV numbers are treated as
    # thousand separators (not decimal separators as in it-IT).  Tableau
    # exports CSV data in English formatting regardless of workbook locale.
    type_list = ", ".join(type_pairs)
    changed_type_line = f'{indent}ChangedType = Table.TransformColumnTypes({final_ref}, {{{type_list}}}, "en-US")'

    # Insert before `in` and update the `in` reference.
    lines.insert(in_idx, changed_type_line)
    new_in_idx = in_idx + 1
    if len(in_parts) >= 2:
        lines[new_in_idx] = in_line.split(None, 1)[0] + "\n" + indent + "ChangedType"
    else:
        lines[new_in_idx + 1] = indent + "ChangedType"

    return "\n".join(lines)


class SemanticModelAssembler:
    """Deterministic assembler: validated decisions → PBIP file tree."""

    def __init__(
        self,
        decisions: SemanticModelDecisions,
        semantic_model_name: str,
    ) -> None:
        self.decisions = decisions
        self.name = semantic_model_name
        self.prefix = f"{semantic_model_name}.SemanticModel"
        self._pre_generate_uuids()

    # ------------------------------------------------------------------
    # UUID pre-generation
    # ------------------------------------------------------------------

    def _pre_generate_uuids(self) -> None:
        """Pre-generate all UUIDs in Python before assembling any files.

        This ensures deterministic, conflict-free identifiers.  The LLM
        is never asked to generate UUIDs — that would risk duplicates
        or malformed values.
        """
        self._logical_id = _uuid4()
        self._table_tags: dict[str, str] = {}
        self._column_tags: dict[tuple[str, str], str] = {}
        self._expression_tags: dict[str, str] = {}
        self._relationship_ids: list[str] = []

        # Detect whether any table has a file-based M query.
        # If so, the assembler will emit a DataFolderPath parameter.
        self._has_file_sources = any("File.Contents" in t.m_query for t in self.decisions.tables)
        if self._has_file_sources:
            self._expression_tags[_DATA_FOLDER_PARAM] = _uuid4()

        for table in self.decisions.tables:
            self._table_tags[table.name] = _uuid4()
            if table.is_calc_group:
                self._column_tags[(table.name, f"{table.name} column")] = _uuid4()
                self._column_tags[(table.name, "Ordinal")] = _uuid4()
            else:
                for col in table.columns:
                    self._column_tags[(table.name, col.name)] = _uuid4()

        for param in self.decisions.parameters:
            self._expression_tags[param.name] = _uuid4()

        for _ in self.decisions.relationships:
            self._relationship_ids.append(_uuid4())

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def assemble(self) -> dict[str, str]:
        """Return ``{relative_path: content_string}`` for every file."""
        p = self.prefix
        files: dict[str, str] = {}

        files[f"{p}/.platform"] = self._render_platform()
        files[f"{p}/definition.pbism"] = self._render_pbism()
        files[f"{p}/.pbi/editorSettings.json"] = self._render_editor_settings()
        files[f"{p}/.pbi/localSettings.json"] = self._render_local_settings()
        files[f"{p}/definition/database.tmdl"] = self._render_database()
        files[f"{p}/definition/model.tmdl"] = self._render_model()
        files[f"{p}/definition/expressions.tmdl"] = self._render_expressions()
        files[f"{p}/definition/relationships.tmdl"] = self._render_relationships()
        files[f"{p}/definition/cultures/en-US.tmdl"] = self._render_culture()
        files[f"{p}/diagramLayout.json"] = self._render_diagram()

        for table in self.decisions.tables:
            files[f"{p}/definition/tables/{table.name}.tmdl"] = self._render_table(table)

        return files

    # ------------------------------------------------------------------
    # Fixed JSON files
    # ------------------------------------------------------------------

    def _render_platform(self) -> str:
        return json.dumps(
            {
                "$schema": SCHEMA_PLATFORM,
                "metadata": {"type": "SemanticModel", "displayName": self.name},
                "config": {"version": "2.0", "logicalId": self._logical_id},
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _render_pbism() -> str:
        return json.dumps(
            {
                "$schema": SCHEMA_PBISM,
                "version": "4.2",
                "settings": {},
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _render_editor_settings() -> str:
        return json.dumps(
            {
                "$schema": SCHEMA_EDITOR,
                "autodetectRelationships": True,
                "parallelQueryLoading": True,
                "typeDetectionEnabled": True,
                "relationshipImportEnabled": True,
                "shouldNotifyUserOfNameConflictResolution": True,
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _render_local_settings() -> str:
        return json.dumps(
            {
                "$schema": SCHEMA_LOCAL,
                "userConsent": {},
            },
            separators=(",", ":"),
        )

    # ------------------------------------------------------------------
    # TMDL files
    # ------------------------------------------------------------------

    def _render_database(self) -> str:
        return f"database {_quote(self.name)}\n{TAB}compatibilityLevel: 1600\n"

    def _render_model(self) -> str:
        d = self.decisions
        culture = d.source_query_culture

        lines: list[str] = [
            "model Model",
            f"{TAB}culture: en-US",
            f"{TAB}defaultPowerBIDataSourceVersion: powerBI_V3",
            f"{TAB}discourageImplicitMeasures",
            f"{TAB}sourceQueryCulture: {culture}",
            f"{TAB}dataAccessOptions",
            f"{TAB}{TAB}legacyRedirects",
            f"{TAB}{TAB}returnErrorValuesAsNull",
            "",
            "queryGroup Dimension",
            f"{TAB}annotation PBI_QueryGroupOrder = 0",
            "",
            "queryGroup Fact",
            f"{TAB}annotation PBI_QueryGroupOrder = 1",
            "",
            "queryGroup Parameters",
            f"{TAB}annotation PBI_QueryGroupOrder = 2",
            "",
        ]

        # PBI_QueryOrder: tables, then DataFolderPath (if file sources),
        # then user-defined parameters — all single-quoted.
        order_items = [_quote(t.name) for t in d.tables]
        if self._has_file_sources:
            order_items.append(_quote(_DATA_FOLDER_PARAM))
        order_items.extend(_quote(p.name) for p in d.parameters)
        query_order = ",".join(order_items)

        lines.append("annotation __PBI_TimeIntelligenceEnabled = 1")
        lines.append(f"annotation PBI_QueryOrder = [{query_order}]")
        lines.append('annotation PBI_ProTooling = ["DevMode"]')
        lines.append("")

        for table in d.tables:
            lines.append(f"ref table {_quote(table.name)}")

        # Explicitly declare all relationships and expressions so that
        # model.tmdl is a self-describing manifest.  PBI Desktop may
        # auto-discover these from individual TMDL files, but emitting
        # them is harmless and more robust across PBI versions, Fabric,
        # and stricter TMDL parsers.
        for i, _rel in enumerate(d.relationships):
            lines.append(f"ref relationship {self._relationship_ids[i]}")

        if self._has_file_sources:
            lines.append(f"ref expression {_quote(_DATA_FOLDER_PARAM)}")
        for param in d.parameters:
            lines.append(f"ref expression {_quote(param.name)}")

        lines.append("ref cultureInfo en-US")

        return "\n".join(lines) + "\n"

    def _render_expressions(self) -> str:
        if not self.decisions.parameters and not self._has_file_sources:
            return ""

        blocks: list[str] = []

        # Auto-generated DataFolderPath parameter for file-based sources.
        # The user sets this once in Power BI → Manage Parameters to point
        # at the folder containing the .pbip file (with trailing backslash).
        if self._has_file_sources:
            tag = self._expression_tags[_DATA_FOLDER_PARAM]
            blocks.append(
                "\n".join(
                    [
                        f"expression {_quote(_DATA_FOLDER_PARAM)} = "
                        f'"C:\\Change\\Me" '
                        f'meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
                        f"{TAB}lineageTag: {tag}",
                        f"{TAB}queryGroup: Parameters",
                        f"{TAB}annotation PBI_NavigationStepName = Navigation",
                        f"{TAB}annotation PBI_ResultType = Text",
                    ]
                )
            )

        for param in self.decisions.parameters:
            tag = self._expression_tags[param.name]
            blocks.append(
                "\n".join(
                    [
                        f"expression {_quote(param.name)} = {param.default_value} "
                        f'meta [IsParameterQuery=true, Type="{param.pbi_type}", IsParameterQueryRequired=true]',
                        f"{TAB}lineageTag: {tag}",
                        f"{TAB}queryGroup: Parameters",
                        f"{TAB}annotation PBI_NavigationStepName = Navigation",
                        f"{TAB}annotation PBI_ResultType = {param.pbi_type}",
                    ]
                )
            )

        return "\n\n".join(blocks) + "\n"

    def _render_relationships(self) -> str:
        if not self.decisions.relationships:
            return ""

        blocks: list[str] = []
        for i, rel in enumerate(self.decisions.relationships):
            rel_id = self._relationship_ids[i]
            lines = [
                f"relationship {rel_id}",
                f"{TAB}fromColumn: {_quote(rel.from_table)}.{_quote(rel.from_column)}",
                f"{TAB}toColumn: {_quote(rel.to_table)}.{_quote(rel.to_column)}",
            ]
            if not rel.is_active:
                lines.append(f"{TAB}isActive: false")
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks) + "\n"

    @staticmethod
    def _render_culture() -> str:
        lines = [
            "cultureInfo en-US",
            f"{TAB}linguisticMetadata =",
            f"{TAB}{TAB}{TAB}{{",
            f'{TAB}{TAB}{TAB}  "Version": "1.0.0",',
            f'{TAB}{TAB}{TAB}  "Language": "en-US"',
            f"{TAB}{TAB}{TAB}}}",
            f"{TAB}{TAB}contentType: json",
        ]
        return "\n".join(lines) + "\n"

    def _render_table(self, table: TableDecision) -> str:
        tag = self._table_tags[table.name]
        lines: list[str] = [
            f"table {_quote(table.name)}",
            f"{TAB}lineageTag: {tag}",
            "",
        ]

        if table.is_calc_group:
            self._render_calc_group_body(table, lines)
        else:
            self._render_regular_table_body(table, lines)

        return "\n".join(lines) + "\n"

    def _render_regular_table_body(
        self,
        table: TableDecision,
        lines: list[str],
    ) -> None:
        """Render columns and the M partition for a regular (non-calc-group) table.

        The M query body passes through deterministic post-processors:
        1. ``_fix_m_let_commas`` — adds missing commas between let steps
        2. ``_fix_m_excel_navigation`` — rewrites Item/Kind to Name-based nav
        3. ``_fix_m_file_paths`` — normalises forward slashes to backslashes
        4. ``_fix_m_csv_quote_style`` — QuoteStyle.None → QuoteStyle.Csv
        5. ``_parameterize_file_paths`` — replaces relative paths with param ref
        6. ``_inject_column_types`` — adds Table.TransformColumnTypes for type safety
        """
        # Columns
        for col in table.columns:
            col_tag = self._column_tags[(table.name, col.name)]
            lines.append(f"{TAB}column {_quote(col.name)}")
            lines.append(f"{TAB}{TAB}dataType: {col.data_type}")
            if col.data_type == "int64":
                lines.append(f"{TAB}{TAB}formatString: 0")
            lines.append(f"{TAB}{TAB}lineageTag: {col_tag}")
            lines.append(f"{TAB}{TAB}summarizeBy: {col.summarize_by}")
            lines.append(f"{TAB}{TAB}sourceColumn: {col.source_column}")
            lines.append("")
            lines.append(f"{TAB}{TAB}annotation SummarizationSetBy = Automatic")
            lines.append("")

        # Partition
        lines.append(f"{TAB}partition {_quote(table.name)} = m")
        lines.append(f"{TAB}{TAB}mode: import")
        lines.append(f"{TAB}{TAB}queryGroup: {table.query_group}")
        lines.append(f"{TAB}{TAB}source =")

        m_body = _fix_m_let_commas(table.m_query.replace("\r\n", "\n"))
        m_body = _fix_m_excel_navigation(m_body)
        m_body = _fix_m_file_paths(m_body)
        m_body = _fix_m_csv_quote_style(m_body)
        m_body = _parameterize_file_paths(m_body)
        m_body = _inject_column_types(m_body, table.columns)
        for m_line in m_body.split("\n"):
            lines.append(f"{TAB}{TAB}{TAB}{TAB}{m_line}")

        lines.append("")
        lines.append(f"{TAB}annotation PBI_NavigationStepName = Navigation")
        lines.append(f"{TAB}annotation PBI_ResultType = Table")

    def _render_calc_group_body(
        self,
        table: TableDecision,
        lines: list[str],
    ) -> None:
        """Render a calculation group table with standard Name + Ordinal columns.

        Calculation groups don't have M queries or user-defined columns.
        Instead they get a calculationGroup block, a Name column (string),
        and an Ordinal column (int64) for sorting.
        """
        lines.append(f"{TAB}calculationGroup")
        for item in table.calc_items:
            lines.append(f"{TAB}{TAB}calculationItem {item} = SELECTEDMEASURE()")
        lines.append("")

        # Standard name column
        cg_col_tag = self._column_tags[(table.name, f"{table.name} column")]
        lines.append(f"{TAB}column {_quote(f'{table.name} column')}")
        lines.append(f"{TAB}{TAB}dataType: string")
        lines.append(f"{TAB}{TAB}lineageTag: {cg_col_tag}")
        lines.append(f"{TAB}{TAB}summarizeBy: none")
        lines.append(f"{TAB}{TAB}sourceColumn: Name")
        lines.append(f"{TAB}{TAB}sortByColumn: Ordinal")
        lines.append("")
        lines.append(f"{TAB}{TAB}annotation SummarizationSetBy = Automatic")
        lines.append("")

        # Standard ordinal column
        ord_tag = self._column_tags[(table.name, "Ordinal")]
        lines.append(f"{TAB}column Ordinal")
        lines.append(f"{TAB}{TAB}dataType: int64")
        lines.append(f"{TAB}{TAB}formatString: 0")
        lines.append(f"{TAB}{TAB}lineageTag: {ord_tag}")
        lines.append(f"{TAB}{TAB}summarizeBy: sum")
        lines.append(f"{TAB}{TAB}sourceColumn: Ordinal")
        lines.append("")
        lines.append(f"{TAB}{TAB}annotation SummarizationSetBy = Automatic")

    # ------------------------------------------------------------------
    # Diagram layout
    # ------------------------------------------------------------------

    @staticmethod
    def _node_height(column_count: int) -> int:
        """Calculate diagram node height based on column count.

        Power BI Desktop uses roughly 24px per column plus an 80px
        header/footer area, capped at 300px for very wide tables.
        """
        return min(80 + column_count * 24, 300)

    def _render_diagram(self) -> str:
        """Build ``diagramLayout.json`` in the format Power BI Desktop expects.

        Key structural requirements discovered by saving from PBI Desktop:
        - Node coordinates wrapped in ``"location": {"x": …, "y": …}``
        - ``zoomValue`` lives inside each diagram object, not at the top level
        - Each diagram carries ``ordinal``, ``scrollPosition``, and boolean flags
        - Each node carries ``zIndex``
        - Top-level ``selectedDiagram`` and ``defaultDiagram`` are required
        """
        nodes: list[dict[str, object]] = []
        fact_count = 0
        dim_count = 0

        for table in self.decisions.tables:
            if table.is_calc_group:
                continue

            tag = self._table_tags[table.name]
            height = self._node_height(len(table.columns))

            if table.query_group == "Fact":
                x = 140 + fact_count * 280
                y = 50
                fact_count += 1
            else:
                x = 577 + dim_count * 280
                y = 50
                dim_count += 1

            nodes.append(
                {
                    "location": {"x": x, "y": y},
                    "nodeIndex": table.name,
                    "nodeLineageTag": tag,
                    "size": {"height": height, "width": 234},
                    "zIndex": 0,
                }
            )

        diagram_name = "All tables"
        return json.dumps(
            {
                "version": "1.1.0",
                "diagrams": [
                    {
                        "ordinal": 0,
                        "scrollPosition": {"x": 0, "y": 0},
                        "nodes": nodes,
                        "name": diagram_name,
                        "zoomValue": 100,
                        "pinKeyFieldsToTop": False,
                        "showExtraHeaderInfo": False,
                        "hideKeyFieldsWhenCollapsed": False,
                        "tablesLocked": False,
                    }
                ],
                "selectedDiagram": diagram_name,
                "defaultDiagram": diagram_name,
            },
            indent=2,
        )
