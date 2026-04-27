"""Deterministic PBIP parsing helpers."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

from Tableau2PowerBI.core.output_dirs import resolve_safe_path
from Tableau2PowerBI.core.source_detection import detect_source_file


@dataclass(frozen=True)
class ExtractedPbipProject:
    """Extracted PBIP project metadata."""

    project_name: str
    metadata: dict[str, Any]


def extract_pbip_metadata(zip_path: str | Path) -> dict[str, Any]:
    """Extract PBIP metadata from a ZIP package and return structured JSON."""
    path = Path(zip_path).resolve()
    detected = detect_source_file(path)
    if detected.source_format != "pbip" or not detected.pbip_entry:
        raise ValueError(f"Expected a PBIP ZIP package, got: {path}")

    with tempfile.TemporaryDirectory(prefix="pbip_extract_") as tmpdir:
        workspace = Path(tmpdir)
        _extract_zip_safely(path, workspace)
        pbip_path = _resolve_archive_path(workspace, detected.pbip_entry)
        metadata = _parse_extracted_pbip(workspace, pbip_path)
        return metadata


def _extract_zip_safely(zip_path: Path, output_dir: Path) -> None:
    try:
        with ZipFile(zip_path, "r") as archive:
            for info in archive.infolist():
                entry = info.filename
                if not entry or entry.endswith("/"):
                    continue
                target = resolve_safe_path(output_dir, entry)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    except BadZipFile as exc:
        raise ValueError(f"Invalid ZIP archive: {zip_path}") from exc


def _resolve_archive_path(root: Path, relative_path: str) -> Path:
    candidate = (root / PurePosixPath(relative_path)).resolve()
    if candidate != root.resolve() and root.resolve() not in candidate.parents:
        raise ValueError(f"Refusing to resolve path outside extracted PBIP root: {relative_path}")
    return candidate


def _resolve_relative_path(root: Path, base_file: Path, relative_path: str) -> Path:
    candidate = (base_file.parent / PurePosixPath(relative_path)).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"Refusing to resolve PBIP-relative path outside extracted root: {relative_path}")
    return candidate


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_extracted_pbip(root: Path, pbip_path: Path) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    project_manifest = _load_json(pbip_path)

    report_rel_path = _extract_report_path(project_manifest)
    if not report_rel_path:
        warnings.append(_warning("missing_report_path", "PBIP manifest does not reference a report artifact path."))
    report_dir = _resolve_relative_path(root, pbip_path, report_rel_path) if report_rel_path else None
    report_info = _parse_report(root, report_dir, warnings) if report_dir else _empty_report()

    semantic_model_rel_path = report_info.get("semantic_model_path")
    semantic_model_dir = (
        _resolve_relative_path(root, report_dir / "definition.pbir", semantic_model_rel_path)
        if report_dir and semantic_model_rel_path
        else None
    )
    semantic_model = _parse_semantic_model(root, semantic_model_dir, warnings) if semantic_model_dir else _empty_model()

    page_count = len(report_info.get("pages", []))
    visuals_count = sum(len(page.get("visuals", [])) for page in report_info.get("pages", []))
    table_count = len(semantic_model.get("tables", []))
    column_count = sum(len(table.get("columns", [])) for table in semantic_model.get("tables", []))
    measure_count = sum(len(table.get("measures", [])) for table in semantic_model.get("tables", []))

    return {
        "source_format": "pbip",
        "datasources": [],
        "worksheets": [],
        "dashboards": [],
        "parameters": [],
        "pbip": {
            "project": {
                "name": pbip_path.stem,
                "pbip_path": _display_path(root, pbip_path),
                "report_path": report_rel_path,
                "semantic_model_path": semantic_model_rel_path,
                "version": project_manifest.get("version"),
                "settings": project_manifest.get("settings") or {},
            },
            "semantic_model": semantic_model,
            "report": report_info,
            "warnings": warnings,
        },
        "summary": {
            "tables": table_count,
            "columns": column_count,
            "measures": measure_count,
            "pages": page_count,
            "visuals": visuals_count,
        },
    }


def _extract_report_path(project_manifest: dict[str, Any]) -> str | None:
    for artifact in project_manifest.get("artifacts", []):
        report = artifact.get("report")
        if isinstance(report, dict) and report.get("path"):
            return str(report["path"])
    return None


def _empty_report() -> dict[str, Any]:
    return {
        "path": None,
        "semantic_model_path": None,
        "pages": [],
        "active_page_name": None,
        "theme": {},
        "settings": {},
    }


def _empty_model() -> dict[str, Any]:
    return {
        "path": None,
        "version": None,
        "model": {},
        "tables": [],
        "relationships": [],
        "cultures": [],
        "expressions": [],
    }


def _display_path(root: Path, path: Path) -> str:
    relative = os.path.relpath(path, start=root)
    if relative in {".", ""}:
        return path.name
    return relative.replace("\\", "/")


def _parse_report(root: Path, report_dir: Path, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    if not report_dir.exists():
        warnings.append(_warning("missing_report", f"Referenced PBIP report folder not found: {report_dir.name}"))
        return _empty_report()

    definition_pbir_path = report_dir / "definition.pbir"
    report_json_path = report_dir / "definition" / "report.json"
    pages_json_path = report_dir / "definition" / "pages" / "pages.json"

    if not definition_pbir_path.exists():
        warnings.append(_warning("missing_definition_pbir", f"Missing report definition.pbir in {report_dir.name}"))
        return _empty_report()

    definition_pbir = _load_json(definition_pbir_path)
    report_json = _load_json(report_json_path) if report_json_path.exists() else {}
    if not report_json_path.exists():
        warnings.append(_warning("missing_report_json", f"Missing report.json in {report_dir.name}"))

    pages_meta = _load_json(pages_json_path) if pages_json_path.exists() else {}
    if not pages_json_path.exists():
        warnings.append(_warning("missing_pages_json", f"Missing pages/pages.json in {report_dir.name}"))

    pages_dir = report_dir / "definition" / "pages"
    page_order = pages_meta.get("pageOrder") or []
    page_names = list(page_order)
    if pages_dir.exists():
        for candidate in sorted(p.name for p in pages_dir.iterdir() if p.is_dir()):
            if candidate not in page_names:
                page_names.append(candidate)

    pages = [_parse_page(pages_dir / page_name, page_name, warnings) for page_name in page_names]

    theme_collection = report_json.get("themeCollection") or {}
    theme = {
        "base_theme_name": (((theme_collection.get("baseTheme") or {}).get("name"))),
        "base_theme_type": (((theme_collection.get("baseTheme") or {}).get("type"))),
    }

    dataset_ref = (((definition_pbir.get("datasetReference") or {}).get("byPath") or {}).get("path"))
    return {
        "path": _display_path(root, report_dir),
        "semantic_model_path": dataset_ref,
        "version": definition_pbir.get("version"),
        "active_page_name": pages_meta.get("activePageName"),
        "settings": report_json.get("settings") or {},
        "theme": {k: v for k, v in theme.items() if v},
        "pages": pages,
    }


def _parse_page(page_dir: Path, page_name: str, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    page_json_path = page_dir / "page.json"
    if not page_json_path.exists():
        warnings.append(_warning("missing_page_json", f"Missing page.json for report page '{page_name}'"))
        return {
            "name": page_name,
            "display_name": page_name,
            "visuals": [],
        }

    page_json = _load_json(page_json_path)
    visuals_dir = page_dir / "visuals"
    visuals = []
    if visuals_dir.exists():
        for visual_dir in sorted(p for p in visuals_dir.iterdir() if p.is_dir()):
            visual_json_path = visual_dir / "visual.json"
            if not visual_json_path.exists():
                warnings.append(
                    _warning("missing_visual_json", f"Missing visual.json in page '{page_name}' visual '{visual_dir.name}'")
                )
                continue
            visuals.append(_parse_visual(_load_json(visual_json_path)))

    return {
        "name": page_json.get("name", page_name),
        "display_name": page_json.get("displayName") or page_json.get("name") or page_name,
        "width": page_json.get("width"),
        "height": page_json.get("height"),
        "display_option": page_json.get("displayOption"),
        "visuals": visuals,
    }


def _parse_visual(visual_json: dict[str, Any]) -> dict[str, Any]:
    visual = visual_json.get("visual") or {}
    query = visual.get("query") or {}
    filter_config = visual_json.get("filterConfig") or {}
    field_bindings = _dedupe_field_refs(
        _collect_field_refs(query) + _collect_field_refs(filter_config)
    )
    visual_group = visual_json.get("visualGroup") or {}
    container_kind = "group" if visual_group else "visual"
    visual_type = visual.get("visualType") or ("group" if container_kind == "group" else None)

    return {
        "name": visual_json.get("name"),
        "visual_type": visual_type,
        "container_kind": container_kind,
        "group_mode": visual_group.get("groupMode"),
        "group_display_name": visual_group.get("displayName"),
        "is_hidden": bool(visual_json.get("isHidden")),
        "position": visual_json.get("position") or {},
        "field_bindings": field_bindings,
        "filters": [
            {
                "name": flt.get("name"),
                "type": flt.get("type"),
                "field_bindings": _dedupe_field_refs(_collect_field_refs(flt.get("field"))),
            }
            for flt in filter_config.get("filters", [])
        ],
    }


def _collect_field_refs(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if isinstance(value, dict):
        column = value.get("Column")
        if isinstance(column, dict):
            entity = (((column.get("Expression") or {}).get("SourceRef") or {}).get("Entity"))
            refs.append(
                {
                    "kind": "column",
                    "entity": entity,
                    "property": column.get("Property"),
                }
            )
        measure = value.get("Measure")
        if isinstance(measure, dict):
            entity = (((measure.get("Expression") or {}).get("SourceRef") or {}).get("Entity"))
            refs.append(
                {
                    "kind": "measure",
                    "entity": entity,
                    "property": measure.get("Property"),
                }
            )
        aggregation = value.get("Aggregation")
        if isinstance(aggregation, dict):
            refs.extend(_collect_field_refs(aggregation.get("Expression")))
        for nested in value.values():
            refs.extend(_collect_field_refs(nested))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_collect_field_refs(item))
    return refs


def _dedupe_field_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    qualified_pairs = {
        (ref.get("kind"), ref.get("property"))
        for ref in refs
        if ref.get("entity") and ref.get("property")
    }
    seen: set[tuple[str | None, str | None, str | None]] = set()
    unique: list[dict[str, Any]] = []
    for ref in refs:
        if not ref.get("entity") and (ref.get("kind"), ref.get("property")) in qualified_pairs:
            continue
        key = (ref.get("kind"), ref.get("entity"), ref.get("property"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


def _parse_semantic_model(root: Path, semantic_model_dir: Path, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    if not semantic_model_dir.exists():
        warnings.append(
            _warning("missing_semantic_model", f"Referenced PBIP semantic model folder not found: {semantic_model_dir.name}")
        )
        return _empty_model()

    definition_pbism_path = semantic_model_dir / "definition.pbism"
    definition_dir = semantic_model_dir / "definition"
    pbism = _load_json(definition_pbism_path) if definition_pbism_path.exists() else {}
    if not definition_pbism_path.exists():
        warnings.append(
            _warning("missing_definition_pbism", f"Missing semantic model definition.pbism in {semantic_model_dir.name}")
        )

    parsed = _parse_tmdl_definition(definition_dir, warnings) if definition_dir.exists() else _empty_model()
    if not definition_dir.exists():
        warnings.append(
            _warning("missing_tmdl_definition", f"Missing semantic model definition folder in {semantic_model_dir.name}")
        )

    parsed["path"] = _display_path(root, semantic_model_dir)
    parsed["version"] = pbism.get("version")
    return parsed


def _parse_tmdl_definition(definition_dir: Path, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    tables: dict[str, dict[str, Any]] = {}
    relationships: list[dict[str, Any]] = []
    expressions: list[dict[str, Any]] = []
    cultures: list[dict[str, Any]] = []
    model_info: dict[str, Any] = {}

    for tmdl_path in sorted(definition_dir.rglob("*.tmdl")):
        rel_parts = tmdl_path.relative_to(definition_dir).parts
        if ".pbi" in rel_parts:
            continue
        if rel_parts[:1] == (".pbi",):
            continue
        parsed = _parse_tmdl_file(tmdl_path)
        _merge_tables(tables, parsed["tables"])
        relationships.extend(parsed["relationships"])
        expressions.extend(parsed["expressions"])
        cultures.extend(parsed["cultures"])
        model_info.update({k: v for k, v in parsed["model"].items() if v not in (None, "", [], {})})

    if not model_info:
        warnings.append(_warning("missing_model_tmdl", "Semantic model metadata did not include model.tmdl properties."))

    return {
        "model": model_info,
        "tables": sorted(tables.values(), key=lambda item: item.get("name") or ""),
        "relationships": relationships,
        "cultures": cultures,
        "expressions": expressions,
    }


def _parse_tmdl_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tables: dict[str, dict[str, Any]] = {}
    relationships: list[dict[str, Any]] = []
    expressions: list[dict[str, Any]] = []
    cultures: list[dict[str, Any]] = []
    model_info: dict[str, Any] = {}

    current_table: dict[str, Any] | None = None
    current_column: dict[str, Any] | None = None
    current_measure: dict[str, Any] | None = None
    current_partition: dict[str, Any] | None = None
    current_relationship: dict[str, Any] | None = None
    current_expression: dict[str, Any] | None = None
    current_culture: dict[str, Any] | None = None

    table_indent = column_indent = measure_indent = partition_indent = relationship_indent = expression_indent = culture_indent = 0
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            i += 1
            continue

        indent = _line_indent(raw)
        content = raw.lstrip(" \t")

        if content.startswith("model "):
            model_info["name"] = _strip_quotes(content[len("model ") :].strip())
            current_table = current_column = current_measure = current_partition = current_relationship = current_expression = None
            current_culture = None
            i += 1
            continue

        if content.startswith("table "):
            table_name = _parse_named_declaration(content, "table")
            current_table = tables.setdefault(
                table_name,
                {"name": table_name, "columns": [], "measures": [], "partitions": []},
            )
            current_column = current_measure = current_partition = None
            current_relationship = current_expression = current_culture = None
            table_indent = indent
            i += 1
            continue

        if content.startswith("column ") and current_table is not None:
            current_column = _parse_column_declaration(content)
            current_table["columns"].append(current_column)
            current_measure = current_partition = None
            current_relationship = current_expression = current_culture = None
            column_indent = indent
            if current_column["is_calculated"]:
                current_column["expression"], i = _consume_declaration_expression(
                    lines,
                    i,
                    indent,
                    current_column.get("expression"),
                )
            else:
                current_column["expression"] = None
                i += 1
            continue

        if content.startswith("measure ") and current_table is not None:
            current_measure = _parse_measure_declaration(content)
            current_table["measures"].append(current_measure)
            current_column = current_partition = None
            current_relationship = current_expression = current_culture = None
            measure_indent = indent
            current_measure["expression"], i = _consume_declaration_expression(
                lines,
                i,
                indent,
                current_measure.get("expression"),
            )
            continue

        if content.startswith("partition ") and current_table is not None:
            current_partition = _parse_partition_declaration(content)
            current_table["partitions"].append(current_partition)
            current_column = current_measure = None
            current_relationship = current_expression = current_culture = None
            partition_indent = indent
            i += 1
            continue

        if content.startswith("relationship "):
            relationship_id = _parse_named_declaration(content, "relationship")
            current_relationship = {"name": relationship_id}
            relationships.append(current_relationship)
            current_column = current_measure = current_partition = None
            current_expression = current_culture = None
            relationship_indent = indent
            i += 1
            continue

        if content.startswith("expression "):
            current_expression = _parse_expression_declaration(content)
            expressions.append(current_expression)
            current_column = current_measure = current_partition = current_relationship = current_culture = None
            expression_indent = indent
            current_expression["expression"], i = _consume_declaration_expression(
                lines,
                i,
                indent,
                current_expression.get("expression"),
            )
            continue

        if content.startswith("cultureInfo "):
            current_culture = {"name": _parse_named_declaration(content, "cultureInfo")}
            cultures.append(current_culture)
            current_column = current_measure = current_partition = current_relationship = current_expression = None
            culture_indent = indent
            i += 1
            continue

        if current_partition is not None and indent > partition_indent and content.startswith("source ="):
            source_lines: list[str] = []
            i += 1
            while i < len(lines):
                next_raw = lines[i]
                next_stripped = next_raw.strip()
                if not next_stripped:
                    source_lines.append("")
                    i += 1
                    continue
                next_indent = _line_indent(next_raw)
                next_content = next_raw.lstrip(" \t")
                if next_indent <= partition_indent and _starts_new_tmdl_entity(next_content):
                    break
                source_lines.append(next_raw.strip("\n"))
                i += 1
            current_partition["source"] = "\n".join(line.rstrip() for line in source_lines).strip()
            continue

        if current_column is not None and indent > column_indent and _assign_tmdl_metadata(current_column, content):
            i += 1
            continue

        if current_measure is not None and indent > measure_indent and _assign_tmdl_metadata(current_measure, content):
            i += 1
            continue

        if current_partition is not None and indent > partition_indent and _assign_tmdl_metadata(current_partition, content):
            i += 1
            continue

        if current_relationship is not None and indent > relationship_indent and _assign_tmdl_metadata(current_relationship, content):
            i += 1
            continue

        if current_expression is not None and indent > expression_indent and _assign_tmdl_metadata(current_expression, content):
            i += 1
            continue

        if current_culture is not None and indent > culture_indent and _assign_tmdl_metadata(current_culture, content):
            i += 1
            continue

        if current_table is not None and indent > table_indent and _assign_tmdl_metadata(current_table, content):
            i += 1
            continue

        if current_expression is None and current_table is None and _assign_tmdl_metadata(model_info, content):
            i += 1
            continue

        i += 1

    for expression in expressions:
        _finalize_expression_metadata(expression)

    return {
        "tables": list(tables.values()),
        "relationships": relationships,
        "expressions": expressions,
        "cultures": cultures,
        "model": model_info,
    }


def _starts_new_tmdl_entity(content: str) -> bool:
    return content.startswith(
        ("table ", "column ", "measure ", "partition ", "relationship ", "expression ", "cultureInfo ")
    )


def _merge_tables(target: dict[str, dict[str, Any]], tables: list[dict[str, Any]]) -> None:
    for table in tables:
        existing = target.setdefault(
            table["name"],
            {"name": table["name"], "columns": [], "measures": [], "partitions": []},
        )
        for key in ("columns", "measures", "partitions"):
            existing[key].extend(table.get(key, []))
        for key, value in table.items():
            if key not in {"name", "columns", "measures", "partitions"} and value not in (None, "", [], {}):
                existing[key] = value


def _parse_named_declaration(content: str, prefix: str) -> str:
    return _strip_quotes(content[len(prefix) :].strip())


def _parse_column_declaration(content: str) -> dict[str, Any]:
    rest = content[len("column ") :].strip()
    if "=" in rest:
        name, expression = rest.split("=", 1)
        return {
            "name": _strip_quotes(name.strip()),
            "expression": expression.strip() or None,
            "is_calculated": True,
        }
    return {"name": _strip_quotes(rest), "expression": None, "is_calculated": False}


def _parse_measure_declaration(content: str) -> dict[str, Any]:
    rest = content[len("measure ") :].strip()
    if "=" in rest:
        name, formula = rest.split("=", 1)
        return {"name": _strip_quotes(name.strip()), "expression": formula.strip()}
    return {"name": _strip_quotes(rest)}


def _parse_partition_declaration(content: str) -> dict[str, Any]:
    rest = content[len("partition ") :].strip()
    name, _, mode = rest.partition("=")
    parsed = {"name": _strip_quotes(name.strip())}
    if mode.strip():
        parsed["kind"] = mode.strip()
    return parsed


def _parse_expression_declaration(content: str) -> dict[str, Any]:
    rest = content[len("expression ") :].strip()
    name, _, expression = rest.partition("=")
    expression_text, meta = _split_expression_definition(expression.strip())
    return {
        "name": _strip_quotes(name.strip()),
        "expression": expression_text,
        "meta": meta,
        "kind": "parameter_query" if meta.get("is_parameter_query") else "expression",
    }


def _split_key_value(content: str) -> tuple[str, str]:
    key, value = content.split(":", 1)
    return key.strip(), value.strip()


def _to_snake_case(value: str) -> str:
    normalised = value.replace("-", "_").replace(" ", "_")
    normalised = re.sub(r"(?<!^)(?=[A-Z][a-z])", "_", normalised)
    normalised = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", normalised)
    normalised = re.sub(r"_+", "_", normalised)
    return normalised.lower()


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _clean_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    return _safe_literal(value)


def _safe_literal(value: str) -> Any:
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return _strip_quotes(value)


def _line_indent(raw: str) -> int:
    return len(raw) - len(raw.lstrip(" \t"))


def _assign_tmdl_metadata(target: dict[str, Any], content: str) -> bool:
    if content.startswith("annotation ") and "=" in content:
        name, raw_value = content[len("annotation ") :].split("=", 1)
        key = _to_snake_case(name.strip())
        value = _clean_scalar(raw_value.strip())
        annotations = target.setdefault("annotations", {})
        annotations[key] = value
        if key == "pbi_query_order":
            target["query_order"] = value
        if key == "pbi_result_type":
            target["result_type"] = value
        return True

    if content.startswith("changedProperty ") and "=" in content:
        _, raw_value = content.split("=", 1)
        target["changed_property"] = _clean_scalar(raw_value.strip())
        return True

    if ":" in content:
        key, value = _split_key_value(content)
        target[_to_snake_case(key)] = _clean_scalar(value)
        return True

    return False


def _consume_declaration_expression(
    lines: list[str],
    start_idx: int,
    entity_indent: int,
    initial_expression: str | None,
) -> tuple[str | None, int]:
    expression_lines: list[str] = []
    expression_started = False
    if initial_expression and initial_expression.strip():
        expression_lines.append(initial_expression.rstrip())
        expression_started = True

    i = start_idx + 1
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            if expression_started:
                expression_lines.append("")
            i += 1
            continue

        indent = _line_indent(raw)
        content = raw.lstrip(" \t")
        if indent <= entity_indent and _starts_new_tmdl_entity(content):
            break
        if indent > entity_indent and _is_tmdl_property_line(content):
            break
        if indent <= entity_indent and not expression_started:
            break

        expression_lines.append(content.rstrip())
        expression_started = True
        i += 1

    expression = "\n".join(line.rstrip() for line in expression_lines).strip()
    return expression or None, i


def _is_tmdl_property_line(content: str) -> bool:
    return ":" in content or (content.startswith("annotation ") and "=" in content) or (
        content.startswith("changedProperty ") and "=" in content
    )


def _split_expression_definition(value: str) -> tuple[str | None, dict[str, Any]]:
    if not value:
        return None, {}

    match = re.match(r"^(?P<expression>.*?)(?:\s+meta\s+(?P<meta>\[.*\]))?$", value)
    if not match:
        return value or None, {}

    expression = (match.group("expression") or "").strip() or None
    meta = _parse_expression_meta(match.group("meta") or "")
    return expression, meta


def _parse_expression_meta(value: str) -> dict[str, Any]:
    if not value.startswith("[") or not value.endswith("]"):
        return {}

    items = _split_top_level_items(value[1:-1])
    meta: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        meta[_to_snake_case(key.strip())] = _clean_scalar(raw_value.strip())
    return meta


def _split_top_level_items(value: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    bracket_depth = 0
    for char in value:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            continue
        if char == "[":
            bracket_depth += 1
            current.append(char)
            continue
        if char == "]":
            bracket_depth = max(0, bracket_depth - 1)
            current.append(char)
            continue
        if char == "," and bracket_depth == 0:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
            continue
        current.append(char)

    trailing = "".join(current).strip()
    if trailing:
        items.append(trailing)
    return items


def _finalize_expression_metadata(expression: dict[str, Any]) -> None:
    meta = expression.get("meta") or {}
    result_type = expression.get("result_type")
    if result_type in (None, ""):
        result_type = meta.get("type")
    if result_type not in (None, ""):
        expression["result_type"] = result_type

    kind = "parameter_query" if meta.get("is_parameter_query") else "expression"
    expression["kind"] = kind


def _warning(code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "warning",
        "message": message,
        "manual_review_required": True,
    }
