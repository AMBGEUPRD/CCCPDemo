"""Deterministic Tableau workbook XML parser.

Extracts structured metadata from ``.twb`` and ``.twbx`` files into a flat
Python dict that can be serialised to JSON.  This module owns **all** XML
parsing logic; no other module should touch ``xml.etree``.

The main class is :class:`TableauWorkbookParser`, which accepts a workbook
file path and exposes :meth:`~TableauWorkbookParser.parse` to return the
full metadata dict.

Standalone functions for TWBX archive handling and connection path resolution
remain module-level because they operate on file paths / dicts rather than
a parsed XML tree.

Key public API:
    :func:`read_twb_file`
        Convenience wrapper — returns the metadata as a JSON string.
    :func:`extract_workbook_metadata`
        Returns the metadata as a ``dict`` (delegates to ``TableauWorkbookParser``).
    :func:`extract_data_files_from_twbx`
        Extracts embedded data files from a TWBX archive.
    :func:`resolve_connection_paths`
        Enriches connection dicts with ``resolved_filename`` and ``relative_path``.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from Tableau2PowerBI.agents.metadata_extractor.tableau_xml_parsing import (
    TABLEAU_VIRTUAL_FIELDS,
    load_tableau_workbook_root,
    parse_field_ref,
    parse_shelf,
)

logger = logging.getLogger(__name__)

_TABLEAU_VIRTUAL_FIELDS = TABLEAU_VIRTUAL_FIELDS

# Keep legacy names available for tests and external callers while avoiding
# extra wrapper functions that only forward to helper implementations.
_parse_field_ref = parse_field_ref
_parse_shelf = parse_shelf


def extract_workbook_metadata(file_path: str) -> dict[str, list[dict[str, Any]]]:
    """Parse a Tableau workbook into structured metadata.

    Delegates to :class:`TableauWorkbookParser` for all XML extraction.

    Returns a dict with top-level keys: ``datasources``, ``worksheets``,
    ``dashboards``, ``actions``, ``parameters``.
    """
    parser = TableauWorkbookParser(file_path)
    return parser.parse()


def read_twb_file(file_path: str) -> str:
    """Parse a Tableau workbook and return the metadata as a JSON string."""
    return json.dumps(extract_workbook_metadata(file_path), indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════
#  TableauWorkbookParser — OOP wrapper around the XML extraction logic
# ═══════════════════════════════════════════════════════════════════════════


class TableauWorkbookParser:
    """Parses a Tableau workbook XML tree into a structured metadata dict.

    The parser loads the XML root element on construction (handling both
    ``.twb`` and ``.twbx`` formats), then exposes :meth:`parse` to walk
    the tree and extract datasources, worksheets, dashboards, actions,
    and parameters.

    All extraction methods are instance methods that reference ``self.root``
    rather than accepting the root element as a parameter, eliminating
    repetitive argument passing.
    """

    def __init__(self, file_path: str) -> None:
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Tableau workbook not found at: {path}")
        self.root: ET.Element = load_tableau_workbook_root(path)

    def parse(self) -> dict[str, list[dict[str, Any]]]:
        """Extract the full metadata dict from the loaded workbook."""
        datasources = self._extract_datasources()
        worksheets = self._extract_worksheets()

        # Resolve auto-generated Calculation_XXXXXXXXX names in shelf field refs.
        # The human-readable caption lives on the calculated_field entry inside each
        # datasource.  We build a workbook-wide {raw_name: caption} index here so
        # the downstream agents and the UI both receive the resolved display name
        # instead of the opaque internal ID.
        calc_index = self._build_calc_index(datasources)
        if calc_index:
            self._resolve_shelf_refs(worksheets, calc_index)

        ds_name_index = self._build_datasource_name_index(datasources)
        if ds_name_index:
            self._resolve_shelf_refs(worksheets, ds_name_index)

        return {
            "datasources": datasources,
            "worksheets": worksheets,
            "dashboards": self._extract_dashboards(),
            "actions": self._extract_actions(),
            "parameters": self._extract_parameters(),
        }

    @staticmethod
    def _build_calc_index(datasources: list[dict[str, Any]]) -> dict[str, str]:
        """Build a workbook-wide mapping of raw Calculation_XXXXXXXXX names to captions.

        Only entries that have a non-empty caption are included — if Tableau did not
        assign a user-visible name we leave the raw ID in place rather than replacing
        it with an empty string.
        """
        index: dict[str, str] = {}
        for ds in datasources:
            for cf in ds.get("calculated_fields", []):
                raw_name = (cf.get("name") or "").strip("[]")
                caption = cf.get("caption")
                if raw_name and caption:
                    index[raw_name] = caption
        return index

    @staticmethod
    def _build_datasource_name_index(datasources: list[dict[str, Any]]) -> dict[str, str]:
        """Build a mapping of hash datasource names to their human-readable captions.

        Only datasources where name and caption differ are included — if they're
        the same there is nothing to resolve.
        """
        return {
            ds["name"]: ds["caption"]
            for ds in datasources
            if ds.get("name") and ds.get("caption") and ds["name"] != ds["caption"]
        }

    @staticmethod
    def _resolve_shelf_refs(
        worksheets: list[dict[str, Any]],
        calc_index: dict[str, str],
    ) -> None:
        """Replace Calculation_XXXXXXXXX field names in shelf refs with their captions.

        Mutates the worksheet dicts in-place — this is intentional because the shelf
        lists are plain dicts we just built; no external reference holds them yet.
        """
        for ws in worksheets:
            for shelf_key in ("cols_shelf", "rows_shelf"):
                for ref in ws.get(shelf_key, []):
                    raw_field = ref.get("field") or ""
                    if raw_field in calc_index:
                        ref["field"] = calc_index[raw_field]

    # ── Datasources ────────────────────────────────────────────────────────

    def _extract_datasources(self) -> list[dict[str, Any]]:
        """Extract all datasources except the built-in 'Parameters' datasource.

        Each datasource includes its connection info, tables, joins,
        relationships, column mappings, columns, calculated fields, groups,
        sets, and metadata records.
        """
        datasources: list[dict[str, Any]] = []
        for datasource in self.root.findall(".//datasources/datasource"):
            datasource_name = datasource.get("name", "")
            if datasource_name == "Parameters":
                continue

            datasource_info: dict[str, Any] = {
                "name": datasource_name,
                "caption": datasource.get("caption"),
                "connection": self._extract_connection(datasource),
                "tables": self._extract_tables(datasource),
                "joins": self._extract_joins(datasource),
                "relationships": self._extract_relationships(datasource),
                "col_mapping": self._extract_col_mapping(datasource),
                "columns": [],
                "calculated_fields": [],
                "groups": self._extract_groups(datasource),
                "sets": [],
                "metadata_records": self._extract_metadata_records(datasource),
            }

            for column in datasource.findall("column"):
                column_info = self._extract_column(column)
                calculation = column.find("calculation")
                if calculation is not None:
                    column_info["formula"] = calculation.get("formula")
                    column_info["formula_class"] = calculation.get("class")
                    datasource_info["calculated_fields"].append(column_info)
                else:
                    datasource_info["columns"].append(column_info)

            datasources.append(datasource_info)

        return datasources

    def _extract_parameters(self) -> list[dict[str, Any]]:
        """Extract parameters from the special 'Parameters' datasource.

        Tableau stores parameters as columns in a virtual datasource
        named 'Parameters'.  Each parameter has a default value, optional
        domain constraints, and allowed values.
        """
        parameters: list[dict[str, Any]] = []
        for datasource in self.root.findall(".//datasources/datasource[@name='Parameters']"):
            for column in datasource.findall("column"):
                calculation = column.find("calculation")
                parameter = self._extract_column(column)
                parameter["default_value"] = calculation.get("formula") if calculation is not None else None
                parameter["domain_type"] = column.get("param-domain-type")

                range_element = column.find("range")
                if range_element is not None:
                    parameter["range"] = {
                        "min": range_element.get("min"),
                        "max": range_element.get("max"),
                        "granularity": range_element.get("granularity"),
                    }

                members = [member.get("value") for member in column.findall(".//member")]
                if members:
                    parameter["allowed_values"] = members

                parameters.append(parameter)

        return parameters

    # ── Worksheets ─────────────────────────────────────────────────────────

    def _extract_worksheets(self) -> list[dict[str, Any]]:
        """Extract all worksheets with their shelves, encodings, filters, etc."""
        worksheets: list[dict[str, Any]] = []
        for worksheet in self.root.findall(".//worksheets/worksheet"):
            cols_shelf_raw = _parse_shelf(worksheet.findtext(".//cols") or "")
            rows_shelf_raw = _parse_shelf(worksheet.findtext(".//rows") or "")

            uses_measure_values = any(
                ref.get("field") in _TABLEAU_VIRTUAL_FIELDS for ref in cols_shelf_raw + rows_shelf_raw
            )

            worksheet_info = {
                "name": worksheet.get("name"),
                "cols_shelf": [ref for ref in cols_shelf_raw if ref.get("field") not in _TABLEAU_VIRTUAL_FIELDS],
                "rows_shelf": [ref for ref in rows_shelf_raw if ref.get("field") not in _TABLEAU_VIRTUAL_FIELDS],
                "uses_measure_values": uses_measure_values,
                "mark_type": None,
                "encodings": self._extract_encodings(worksheet),
                "filters": self._extract_filters(worksheet),
                "table_calculations": self._extract_table_calculations(worksheet),
                "reference_lines": self._extract_reference_lines(worksheet),
                "sorts": self._extract_sorts(worksheet),
                "title": None,
            }

            mark = worksheet.find(".//mark")
            if mark is not None:
                worksheet_info["mark_type"] = mark.get("class")

            title_element = worksheet.find(".//title/formatted-text/run")
            if title_element is not None:
                worksheet_info["title"] = title_element.text

            worksheets.append(worksheet_info)

        return worksheets

    # ── Dashboards ─────────────────────────────────────────────────────────

    def _extract_dashboards(self) -> list[dict[str, Any]]:
        """Extract dashboards with their sheet references and zone layouts."""
        dashboards: list[dict[str, Any]] = []
        for dashboard in self.root.findall(".//dashboards/dashboard"):
            size = dashboard.find("size")
            # Preserve sheet insertion order while deduplicating by name.
            sheet_names: dict[str, None] = {}
            layout_zones: list[dict[str, Any]] = []

            for zone in dashboard.findall(".//zone"):
                name = zone.get("name")
                if not name:
                    continue

                sheet_names.setdefault(name, None)
                layout_zones.append(
                    {
                        "name": name,
                        "type": zone.get("type"),
                        "x": zone.get("x"),
                        "y": zone.get("y"),
                        "w": zone.get("w"),
                        "h": zone.get("h"),
                    }
                )

            dashboards.append(
                {
                    "name": dashboard.get("name"),
                    "size": size.attrib if size is not None else {},
                    "sheets": list(sheet_names),
                    "layout_zones": layout_zones,
                }
            )

        return dashboards

    # ── Actions ────────────────────────────────────────────────────────────

    def _extract_actions(self) -> list[dict[str, Any]]:
        """Extract dashboard actions (filter, highlight, URL, etc.)."""
        return [
            {
                "name": action.get("name"),
                "type": action.get("type"),
                "source_sheet": action.get("source-sheet"),
                "target_sheet": action.get("target-sheet"),
                "fields": action.get("fields"),
                "url": action.get("url"),
            }
            for action in self.root.findall(".//actions/action")
        ]

    # ── Datasource child extractors ───────────────────────────────────────

    @staticmethod
    def _extract_connection(datasource: ET.Element) -> dict[str, Any]:
        """Extract connection info generically from a datasource's ``<connection>`` element.

        Captures **every** XML attribute on the ``<connection>`` element and
        normalises a few standard names for downstream consistency:

        * ``class`` → ``type`` (the connection type identifier)
        * ``dbname`` → ``database`` (kept alongside ``dbname`` for clarity)

        Also detects ``first_row_header`` from the ``<columns header='yes'>``
        attribute on ``<relation>`` elements (CSV / text sources).
        """
        named_connection = datasource.find(".//named-connection")
        if named_connection is None:
            return {}

        connection = named_connection.find("connection")
        if connection is None:
            return {}

        # Capture ALL attributes generically so new connection types work automatically.
        connection_info: dict[str, Any] = dict(connection.attrib)

        # Normalise well-known attribute names for backward compatibility.
        if "class" in connection_info:
            connection_info["type"] = connection_info.pop("class")
        if "dbname" in connection_info and "database" not in connection_info:
            connection_info["database"] = connection_info["dbname"]

        # Detect first-row-is-header from <columns header='yes'>.
        columns_el = datasource.find(".//relation[@type='table']/columns")
        if columns_el is not None and columns_el.get("header") == "yes":
            connection_info["first_row_header"] = True
        else:
            for attr in datasource.findall(".//metadata-record[@class='capability']//attribute[@name='header-row']"):
                if attr.text and attr.text.strip().strip('"') == "true":
                    connection_info["first_row_header"] = True
                    break

        return {key: value for key, value in connection_info.items() if value}

    @staticmethod
    def _extract_tables(datasource: ET.Element) -> list[dict[str, Any]]:
        """Extract physical table entries from ``<relation type='table'>`` elements.

        Deduplicates by name to avoid the empty shells Tableau sometimes emits.
        """
        tables: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for relation in datasource.findall(".//relation[@type='table']"):
            name = relation.get("name")
            physical_table = relation.get("table")
            if not name or name in seen_names:
                continue

            seen_names.add(name)
            tables.append(
                {
                    "name": name,
                    "physical_table": physical_table,
                    "columns": [
                        {
                            "name": column.get("name"),
                            "datatype": column.get("datatype"),
                            "ordinal": int(column.get("ordinal", 0)),
                        }
                        for column in relation.findall("columns/column")
                    ],
                }
            )

        return tables

    @staticmethod
    def _extract_joins(datasource: ET.Element) -> list[dict[str, Any]]:
        """Extract join definitions from ``<relation type='join'>`` elements.

        Captures the join type (inner/left/right), left/right table names,
        and the join condition expression.
        """
        joins: list[dict[str, Any]] = []
        for relation in datasource.findall(".//relation[@type='join']"):
            child_tables = relation.findall("relation[@type='table']")
            left_table = child_tables[0].get("name") if len(child_tables) > 0 else None
            right_table = child_tables[1].get("name") if len(child_tables) > 1 else None

            clause_expression = relation.find(".//clause/expression")
            left_field = None
            right_field = None
            condition = None
            if clause_expression is not None:
                condition = clause_expression.get("op")
                key_expressions = clause_expression.findall("expression")
                if len(key_expressions) >= 1:
                    left_field = _parse_field_ref(key_expressions[0].get("op", ""))
                if len(key_expressions) >= 2:
                    right_field = _parse_field_ref(key_expressions[1].get("op", ""))

            joins.append(
                {
                    "join_type": relation.get("join"),
                    "left_table": left_table,
                    "right_table": right_table,
                    "condition": condition,
                    "left_field": left_field,
                    "right_field": right_field,
                }
            )

        return joins

    @staticmethod
    def _extract_relationships(datasource: ET.Element) -> list[dict[str, Any]]:
        """Extract relationships from the datasource ``<object-graph>``.

        Resolves Tableau's internal object IDs to caption-based names.
        """
        object_graph = datasource.find("object-graph")
        if object_graph is None:
            return []

        id_to_caption = {obj.get("id", ""): obj.get("caption", "") for obj in object_graph.findall("objects/object")}

        relationships: list[dict[str, Any]] = []
        for relationship in object_graph.findall("relationships/relationship"):
            expression = relationship.find("expression")
            left_field = None
            right_field = None
            if expression is not None:
                operands = expression.findall("expression")
                if len(operands) >= 1:
                    left_field = operands[0].get("op")
                if len(operands) >= 2:
                    right_field = operands[1].get("op")

            first_end_point = relationship.find("first-end-point")
            second_end_point = relationship.find("second-end-point")
            left_table = (
                id_to_caption.get(first_end_point.get("object-id", ""), "") if first_end_point is not None else None
            )
            right_table = (
                id_to_caption.get(second_end_point.get("object-id", ""), "") if second_end_point is not None else None
            )

            relationships.append(
                {
                    "left_table": left_table,
                    "right_table": right_table,
                    "left_field": left_field,
                    "right_field": right_field,
                    "cardinality": "many-to-one",
                }
            )

        return relationships

    @staticmethod
    def _extract_col_mapping(datasource: ET.Element) -> list[dict[str, str | None]]:
        """Extract logical-to-physical column mappings from ``<cols>/<map>``."""
        connection = datasource.find("connection")
        if connection is None:
            return []

        cols_element = connection.find("cols")
        if cols_element is None:
            return []

        return [
            {
                "logical_field": mapping.get("key"),
                "physical_column": mapping.get("value"),
            }
            for mapping in cols_element.findall("map")
        ]

    @staticmethod
    def _extract_column(column: ET.Element) -> dict[str, Any]:
        """Extract a single column definition from a ``<column>`` element."""
        return {
            "name": column.get("name"),
            "caption": column.get("caption"),
            "datatype": column.get("datatype"),
            "role": column.get("role"),
            "type": column.get("type"),
            "hidden": column.get("hidden") == "true",
            "default_aggregation": column.get("default-aggregation"),
            "semantic_role": column.get("semantic-role"),
        }

    @staticmethod
    def _extract_groups(datasource: ET.Element) -> list[dict[str, Any]]:
        """Extract group definitions from a datasource."""
        return [
            {
                "name": group.get("name"),
                "caption": group.get("caption"),
                "members": [member.get("name") for member in group.findall("member")],
            }
            for group in datasource.findall(".//group")
        ]

    @staticmethod
    def _extract_metadata_records(datasource: ET.Element) -> list[dict[str, Any]]:
        """Extract metadata records (column‐level type/name/aggregation info)."""
        return [
            {
                "class": metadata_record.get("class"),
                "local_name": metadata_record.findtext("local-name"),
                "local_type": metadata_record.findtext("local-type"),
                "remote_name": metadata_record.findtext("remote-name"),
                "remote_type": metadata_record.findtext("remote-type"),
                "aggregation": metadata_record.findtext("aggregation"),
                "nullable": metadata_record.findtext("contains-null"),
            }
            for metadata_record in datasource.findall(".//metadata-record")
        ]

    # ── Worksheet child extractors ────────────────────────────────────────

    @staticmethod
    def _extract_encodings(worksheet: ET.Element) -> list[dict[str, Any]]:
        """Extract visual encodings (color, size, shape, etc.) from a worksheet."""
        return [
            {
                "type": encoding.get("type"),
                "field": _parse_field_ref(encoding.get("field") or ""),
                "aggregation": encoding.get("aggregation"),
                "binsize": encoding.get("binsize"),
            }
            for encoding in worksheet.findall(".//encoding")
        ]

    @staticmethod
    def _extract_filters(worksheet: ET.Element) -> list[dict[str, Any]]:
        """Extract filter definitions from a worksheet."""
        filters: list[dict[str, Any]] = []
        for filter_element in worksheet.findall(".//filter"):
            filter_info: dict[str, Any] = {
                "class": filter_element.get("class"),
                "column": _parse_field_ref(filter_element.get("column") or ""),
                "filter_group": filter_element.get("filter-group"),
            }
            range_element = filter_element.find("range")
            if range_element is not None:
                filter_info["range"] = {
                    "min": range_element.get("min"),
                    "max": range_element.get("max"),
                }

            members = [
                member.get("value")
                for member in filter_element.findall(".//member")
                if member.get("ui-enumeration") == "inclusive"
            ]
            if members:
                filter_info["included_values"] = members

            filters.append(filter_info)

        return filters

    @staticmethod
    def _extract_table_calculations(worksheet: ET.Element) -> list[dict[str, Any]]:
        """Extract table calculation definitions."""
        return [
            {
                "type": table_calc.get("type"),
                "ordering_type": table_calc.get("ordering-type"),
                "rank_options": table_calc.get("rank-options"),
                "pane_summarization": table_calc.get("pane-summarization"),
            }
            for table_calc in worksheet.findall(".//table-calc")
        ]

    @staticmethod
    def _extract_reference_lines(worksheet: ET.Element) -> list[dict[str, Any]]:
        """Extract reference line definitions."""
        return [
            {
                "formula": reference_line.get("formula"),
                "label_type": reference_line.get("label-type"),
                "scope": reference_line.get("scope"),
                "axis_column": _parse_field_ref(reference_line.get("axis-column") or ""),
                "value_column": _parse_field_ref(reference_line.get("value-column") or ""),
            }
            for reference_line in worksheet.findall(".//reference-line")
        ]

    @staticmethod
    def _extract_sorts(worksheet: ET.Element) -> list[dict[str, Any]]:
        """Extract sort definitions (computed and manual sorts)."""
        return [
            {
                "type": sort.tag,
                "column": _parse_field_ref(sort.get("column") or ""),
                "direction": sort.get("direction"),
            }
            for sort in worksheet.findall(".//computed-sort") + worksheet.findall(".//manual-sort")
        ]
