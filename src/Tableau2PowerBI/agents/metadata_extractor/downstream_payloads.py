"""Downstream payload builder.

Decomposes a full ``tableau_metadata`` dict (as produced by
``metadata_extractor.py``) into focused sub-JSONs, one per specialist agent.

Sub-JSON files written under ``data/output/tableau_metadata_extractor_agent/<workbook>/``:

============================================  ================================================
File                                          Consumer
============================================  ================================================
``semantic_model_input.json``                 ``pbip_semantic_model_generator_agent``
``report_input.json``                         ``pbip_report_generator_agent``
``connections_input.json``                    ``pbip_connections_agent`` (gateway / data source)
``parameters_input.json``                     ``pbip_parameters_agent`` (What-if / field params)
``functional_doc_input_slim.json``            ``tableau_functional_doc_agent`` fallback input
============================================  ================================================

The :class:`DownstreamPayloadBuilder` is the main entry point.  Instantiate
it with the full metadata dict and call :meth:`build_all_payload_files` to write every
sub-JSON in one go, or call individual ``build_*`` methods for fine-grained
control.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MetadataDict = dict[str, Any]
PayloadDict = dict[str, Any]
FUNCTIONAL_DOC_INPUT_SLIM_FILENAME = "functional_doc_input_slim.json"


# ═══════════════════════════════════════════════════════════════════════════
#  Private helpers — pure data transforms
# ═══════════════════════════════════════════════════════════════════════════


def _compact_mapping(mapping: PayloadDict) -> PayloadDict:
    """Remove keys whose values are ``None``, empty containers, or empty strings."""
    return {
        key: value
        for key, value in mapping.items()
        if value is not None and value != [] and value != {} and value != ""
    }


def _strip_raw(obj: Any) -> Any:
    """Remove the redundant ``raw`` key from every parsed field-reference dict."""
    if isinstance(obj, dict):
        return {key: _strip_raw(value) for key, value in obj.items() if key != "raw"}
    if isinstance(obj, list):
        return [_strip_raw(item) for item in obj]
    return obj


def _slim_physical_column(metadata_record: MetadataDict) -> MetadataDict | None:
    """Keep only ``class='column'`` records with a valid ``local_name``."""
    if metadata_record.get("class") != "column" or not metadata_record.get("local_name"):
        return None

    return {
        "local_name": metadata_record.get("local_name"),
        "local_type": metadata_record.get("local_type"),
        "remote_name": metadata_record.get("remote_name"),
    }


def _project_fields(source: MetadataDict, fields: list[str]) -> PayloadDict:
    """Return a compact mapping containing only the requested keys."""
    return _compact_mapping({field: source.get(field) for field in fields})


def _slim_column(column: MetadataDict) -> PayloadDict:
    """Project only the column fields useful for functional documentation."""
    return _project_fields(
        column,
        ["name", "caption", "datatype", "role", "description"],
    )


def _slim_calculated_field(calculated_field: MetadataDict) -> PayloadDict:
    """Project only the calculated field fields useful for FDD prompts."""
    return _project_fields(
        calculated_field,
        ["name", "caption", "formula", "datatype", "role", "description"],
    )


def _slim_parameter(parameter: MetadataDict) -> PayloadDict:
    """Project only the parameter fields useful for functional documentation."""
    return _project_fields(
        parameter,
        [
            "name",
            "caption",
            "datatype",
            "default_value",
            "current_value",
            "allowable_values",
            "range",
        ],
    )


def _slim_action(action: MetadataDict) -> PayloadDict:
    """Project only the action fields useful for functional documentation."""
    projected = _project_fields(
        action,
        [
            "name",
            "caption",
            "type",
            "source_sheet",
            "target_sheet",
            "source_dashboard",
            "target_dashboard",
            "field_mappings",
            "filters",
        ],
    )
    return _compact_mapping(_strip_raw(projected))


def _slim_worksheet(worksheet: MetadataDict) -> PayloadDict:
    """Project a balanced worksheet view for functional documentation."""
    projected = _project_fields(
        worksheet,
        [
            "name",
            "title",
            "caption",
            "worksheet_type",
            "viz_type",
            "mark_type",
            "datasource_dependencies",
            "rows_shelf",
            "cols_shelf",
            "filters",
            "detail_shelf",
            "color_shelf",
            "label_shelf",
            "size_shelf",
            "tooltip_shelf",
            "pages_shelf",
            "text_shelf",
            "table_calculations",
            "reference_lines",
        ],
    )
    return _compact_mapping(_strip_raw(projected))


def _slim_dashboard(dashboard: MetadataDict) -> PayloadDict:
    """Project a balanced dashboard view for functional documentation."""
    return _project_fields(
        dashboard,
        ["name", "title", "caption", "size", "sheets"],
    )


# ═══════════════════════════════════════════════════════════════════════════
#  DownstreamPayloadBuilder
# ═══════════════════════════════════════════════════════════════════════════


class DownstreamPayloadBuilder:
    """Builds focused sub-JSON payloads from full Tableau metadata.

    Each ``build_*`` method produces a dict suitable for one downstream
    agent.  :meth:`build_all_payload_files` writes every payload to disk as numbered
    JSON files.

    Datasource preparation (deduplication, filtering empty shells) is
    done once on construction and shared across all builders, avoiding
    redundant work.
    """

    def __init__(self, metadata: MetadataDict) -> None:
        self.metadata = metadata
        self.prepared_datasources = self._prepare_datasources(
            metadata.get("datasources", []),
        )

    # ── Datasource preparation ─────────────────────────────────────────

    @staticmethod
    def _prepare_datasources(raw_datasources: list[MetadataDict]) -> list[MetadataDict]:
        """Return only datasources that carry real content, deduplicated by name.

        Tableau repeats the same federated datasource name many times as
        empty shells — this filters them out.
        """
        seen: set[str] = set()
        prepared: list[MetadataDict] = []
        for datasource in raw_datasources:
            name = datasource.get("name", "")
            has_content = (
                datasource.get("columns") or datasource.get("calculated_fields") or datasource.get("metadata_records")
            )
            if not has_content or name in seen:
                continue

            seen.add(name)
            prepared.append(datasource)

        return prepared

    # ── Individual payload builders ────────────────────────────────────

    def build_semantic_model_input(self) -> PayloadDict:
        """Build the semantic model input for the LLM agent."""
        datasources = [self._semantic_model_datasource(ds) for ds in self.prepared_datasources]
        return _compact_mapping(
            {
                "parameters": self.metadata.get("parameters"),
                "datasources": datasources,
            }
        )

    def build_report_input(self) -> PayloadDict:
        """Build the report input for the report generator agent."""
        datasource_index = {ds["name"]: ds.get("caption") or ds["name"] for ds in self.prepared_datasources}
        worksheets = [_compact_mapping(_strip_raw(ws)) for ws in self.metadata.get("worksheets", [])]
        dashboards = [
            _compact_mapping(
                {
                    "name": db["name"],
                    "size": db.get("size"),
                    "sheets": db.get("sheets"),
                    "layout_zones": db.get("layout_zones"),
                }
            )
            for db in self.metadata.get("dashboards", [])
        ]
        actions = [compact for compact in (_compact_mapping(a) for a in self.metadata.get("actions", [])) if compact]
        # Include only datasources that have calculated fields — the report visuals
        # agent needs these to resolve Calculation_XXXXXXXXX field name references.
        datasources = [
            _compact_mapping(
                {
                    "name": ds.get("name"),
                    "caption": ds.get("caption"),
                    "calculated_fields": ds.get("calculated_fields"),
                }
            )
            for ds in self.prepared_datasources
            if ds.get("calculated_fields")
        ]

        return _compact_mapping(
            {
                "datasource_index": datasource_index,
                "worksheets": worksheets,
                "dashboards": dashboards,
                "actions": actions,
                "datasources": datasources or None,
            }
        )

    def build_connections_input(self) -> PayloadDict:
        """Build the connections input for the gateway/data-source agent."""
        datasources = [self._connection_datasource(ds) for ds in self.prepared_datasources]
        return {"datasources": datasources}

    def build_parameters_input(self) -> PayloadDict:
        """Build the parameters input for the What-if/field-parameter agent."""
        return _compact_mapping({"parameters": self.metadata.get("parameters", [])})

    def build_functional_doc_input_slim(self) -> PayloadDict:
        """Build a slimmed metadata payload for the functional doc agent."""
        datasources = [self._functional_doc_datasource(ds) for ds in self.prepared_datasources]
        worksheets = [
            slimmed for slimmed in (_slim_worksheet(ws) for ws in self.metadata.get("worksheets", [])) if slimmed
        ]
        dashboards = [
            slimmed for slimmed in (_slim_dashboard(db) for db in self.metadata.get("dashboards", [])) if slimmed
        ]
        parameters = [
            slimmed for slimmed in (_slim_parameter(p) for p in self.metadata.get("parameters", [])) if slimmed
        ]
        actions = [slimmed for slimmed in (_slim_action(a) for a in self.metadata.get("actions", [])) if slimmed]

        return _compact_mapping(
            {
                "dashboards": dashboards,
                "worksheets": worksheets,
                "datasources": datasources,
                "parameters": parameters,
                "actions": actions,
            }
        )

    # ── Batch write ────────────────────────────────────────────────────

    def build_all_payload_files(self, output_dir: Path) -> dict[str, Path]:
        """Build and write every sub-JSON payload to *output_dir*.

        Returns a mapping ``{payload_name: file_path}`` for each file
        written.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        builders = {
            "semantic_model_input": self.build_semantic_model_input,
            "report_input": self.build_report_input,
            "connections_input": self.build_connections_input,
            "parameters_input": self.build_parameters_input,
            "functional_doc_input_slim": self.build_functional_doc_input_slim,
        }

        written: dict[str, Path] = {}
        for name, builder_fn in builders.items():
            payload = builder_fn()
            path = output_dir / f"{name}.json"
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            written[name] = path

        return written

    # ── Datasource transformers ────────────────────────────────────────

    @staticmethod
    def _strip_internal_connection_fields(connection: MetadataDict | None) -> MetadataDict | None:
        """Remove ``resolved_filename`` — an implementation detail that must not
        reach the LLM prompt (it's an absolute machine-specific path)."""
        if not connection:
            return connection
        return {k: v for k, v in connection.items() if k != "resolved_filename"}

    @classmethod
    def _semantic_model_datasource(cls, datasource: MetadataDict) -> PayloadDict:
        """Shape a datasource for the semantic model generator agent."""
        physical_columns = [
            slimmed
            for slimmed in (_slim_physical_column(rec) for rec in datasource.get("metadata_records", []))
            if slimmed
        ]
        columns = [col for col in datasource.get("columns", []) if not (col.get("name") or "").startswith("[:")]
        groups = [grp for grp in datasource.get("groups", []) if grp.get("members")]

        return _compact_mapping(
            {
                "name": datasource.get("caption") or datasource.get("name"),
                "connection": cls._strip_internal_connection_fields(datasource.get("connection")),
                "tables": datasource.get("tables"),
                "joins": datasource.get("joins"),
                "relationships": datasource.get("relationships"),
                "col_mapping": datasource.get("col_mapping"),
                "columns": columns,
                "calculated_fields": datasource.get("calculated_fields"),
                "physical_columns": physical_columns,
                "groups": groups,
                "sets": datasource.get("sets"),
            }
        )

    @staticmethod
    def _connection_datasource(datasource: MetadataDict) -> PayloadDict:
        """Shape a datasource for the connections/gateway agent."""
        physical_tables = [
            table.get("physical_table") or table.get("name")
            for table in datasource.get("tables", [])
            if table.get("physical_table") or table.get("name")
        ]
        return _compact_mapping(
            {
                "name": datasource.get("caption") or datasource.get("name"),
                "connection": datasource.get("connection"),
                "physical_tables": physical_tables,
            }
        )

    @staticmethod
    def _functional_doc_datasource(datasource: MetadataDict) -> PayloadDict:
        """Shape a datasource for functional documentation prompts."""
        # Filter [:TableauInternal] columns (same pattern as _semantic_model_datasource)
        columns = [
            slimmed
            for slimmed in (
                _slim_column(col)
                for col in datasource.get("columns", [])
                if not (col.get("name") or "").startswith("[:")
            )
            if slimmed
        ]
        calculated_fields = [
            slimmed
            for slimmed in (_slim_calculated_field(field) for field in datasource.get("calculated_fields", []))
            if slimmed
        ]
        # Connection: type only (no filenames/servers/paths)
        connection_type = (datasource.get("connection") or {}).get("type")
        # Tables: name only
        table_names = [{"name": t["name"]} for t in datasource.get("tables", []) if t.get("name")]
        # Groups: non-empty members only (same filter as semantic model builder)
        groups = [grp for grp in datasource.get("groups", []) if grp.get("members")]

        return _compact_mapping(
            {
                "name": datasource.get("name"),
                "caption": datasource.get("caption"),
                "connection": _compact_mapping({"type": connection_type}) if connection_type else None,
                "tables": table_names,
                "joins": datasource.get("joins"),
                "relationships": datasource.get("relationships"),
                "columns": columns,
                "calculated_fields": calculated_fields,
                "groups": groups,
            }
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Backward-compatible module-level API
# ═══════════════════════════════════════════════════════════════════════════
# These thin wrappers maintain the existing public interface used by tests
# and the extractor agent.  New code should use DownstreamPayloadBuilder
# directly.


def build_semantic_model_input(metadata: MetadataDict, prepared_datasources: list[MetadataDict]) -> PayloadDict:
    """Build the semantic model input payload (backward-compatible wrapper)."""
    builder = DownstreamPayloadBuilder.__new__(DownstreamPayloadBuilder)
    builder.metadata = metadata
    builder.prepared_datasources = prepared_datasources
    return builder.build_semantic_model_input()


def build_report_input(metadata: MetadataDict, prepared_datasources: list[MetadataDict]) -> PayloadDict:
    """Build the report input payload (backward-compatible wrapper)."""
    builder = DownstreamPayloadBuilder.__new__(DownstreamPayloadBuilder)
    builder.metadata = metadata
    builder.prepared_datasources = prepared_datasources
    return builder.build_report_input()


def build_connections_input(metadata: MetadataDict, prepared_datasources: list[MetadataDict]) -> PayloadDict:
    """Build the connections input payload (backward-compatible wrapper)."""
    builder = DownstreamPayloadBuilder.__new__(DownstreamPayloadBuilder)
    builder.metadata = metadata
    builder.prepared_datasources = prepared_datasources
    return builder.build_connections_input()


def build_parameters_input(metadata: MetadataDict, prepared_datasources: list[MetadataDict]) -> PayloadDict:
    """Build the parameters input payload (backward-compatible wrapper)."""
    builder = DownstreamPayloadBuilder.__new__(DownstreamPayloadBuilder)
    builder.metadata = metadata
    builder.prepared_datasources = prepared_datasources
    return builder.build_parameters_input()


def build_functional_doc_input_slim(metadata: MetadataDict) -> PayloadDict:
    """Build the slim functional documentation payload."""
    builder = DownstreamPayloadBuilder(metadata)
    return builder.build_functional_doc_input_slim()


def build_all_payload_files(metadata: MetadataDict, output_dir: Path) -> dict[str, Path]:
    """Build and write all payloads (backward-compatible wrapper)."""
    builder = DownstreamPayloadBuilder(metadata)
    return builder.build_all_payload_files(output_dir)
