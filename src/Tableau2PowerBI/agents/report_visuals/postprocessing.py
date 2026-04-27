"""Post-processing helpers for PBIR report generation."""

from __future__ import annotations

import json
import logging

from Tableau2PowerBI.core.llm_output_parsing import recover_malformed_json


def fix_pbir_enums(
    files: dict[str, str],
    display_option_map: dict[int, str],
    layout_optimization_map: dict[int, str],
    logger: logging.Logger,
) -> dict[str, str]:
    """Convert integer enum values to strings in PBIR JSON files."""
    updated_files: dict[str, str] = {}
    fixed = 0

    for path, content in files.items():
        needs_rewrite = False

        if path.endswith("/page.json") and "/pages/" in path:
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                updated_files[path] = content
                continue

            val = data.get("displayOption")
            if isinstance(val, int):
                mapped = display_option_map.get(val)
                if mapped is not None:
                    data["displayOption"] = mapped
                    needs_rewrite = True
                    fixed += 1
                else:
                    logger.warning("Unknown displayOption %d in %s", val, path)

        elif path.endswith("/report.json"):
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                updated_files[path] = content
                continue

            val = data.get("layoutOptimization")
            if isinstance(val, int):
                mapped = layout_optimization_map.get(val)
                if mapped is not None:
                    data["layoutOptimization"] = mapped
                    needs_rewrite = True
                    fixed += 1
                else:
                    logger.warning("Unknown layoutOptimization %d in %s", val, path)
        else:
            updated_files[path] = content
            continue

        if needs_rewrite:
            updated_files[path] = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            updated_files[path] = content

    if fixed:
        logger.info("Fixed PBIR int->string enums: %d", fixed)

    return updated_files


def sanitize_visuals(
    files: dict[str, str],
    logger: logging.Logger,
) -> tuple[dict[str, str], dict[str, int]]:
    """Single-pass sanitizer for all visual.json files."""
    updated_files: dict[str, str] = {}
    metrics: dict[str, int] = {
        "configs_stripped": 0,
        "stubs_dropped": 0,
        "positions_injected": 0,
        "structure_fixed": 0,
        "projections_wrapped": 0,
    }
    default_position = {
        "x": 0,
        "y": 0,
        "z": 0,
        "width": 400,
        "height": 300,
        "tabOrder": 0,
    }

    for path, content in files.items():
        if not (path.endswith("/visual.json") and "/visuals/" in path):
            updated_files[path] = content
            continue

        recovered_from_bad_json = False
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            recovered = recover_malformed_json(content)
            if recovered is not None:
                data = recovered
                recovered_from_bad_json = True
                logger.warning(
                    "Visual JSON recovered from bad escapes: %s",
                    path.split("/visuals/")[-1] if "/visuals/" in path else path,
                )
            else:
                updated_files[path] = content
                continue

        modified = recovered_from_bad_json
        short_name = path.split("/visuals/")[-1] if "/visuals/" in path else path

        has_position = "position" in data
        has_visual = "visual" in data

        if not has_position and not has_visual:
            metrics["stubs_dropped"] += 1
            logger.warning("Dropped empty visual stub: %s", short_name)
            continue

        if not has_position and has_visual:
            data["position"] = default_position
            metrics["positions_injected"] += 1
            modified = True
            logger.warning("Injected default position for: %s", short_name)

        visual_obj = data.get("visual", {})
        if "config" in visual_obj:
            del visual_obj["config"]
            metrics["configs_stripped"] += 1
            modified = True

        query_obj = visual_obj.get("query", {})

        if "drillFilterOtherVisuals" in query_obj:
            visual_obj["drillFilterOtherVisuals"] = query_obj.pop("drillFilterOtherVisuals")
            metrics["structure_fixed"] += 1
            modified = True

        if "drillFilterOtherVisuals" in data and visual_obj is not None:
            visual_obj["drillFilterOtherVisuals"] = data.pop("drillFilterOtherVisuals")
            metrics["structure_fixed"] += 1
            modified = True

        if "filterConfig" in visual_obj:
            data["filterConfig"] = visual_obj.pop("filterConfig")
            metrics["structure_fixed"] += 1
            modified = True

        for filt in data.get("filterConfig", {}).get("filters", []):
            filt_field = filt.get("field")
            if isinstance(filt_field, dict) and "active" in filt_field:
                del filt_field["active"]
                metrics["structure_fixed"] += 1
                modified = True

        query_state = query_obj.get("queryState", {})
        if isinstance(query_state, dict):
            for role_name, role_val in query_state.items():
                if isinstance(role_val, list):
                    query_state[role_name] = {"projections": role_val}
                    metrics["projections_wrapped"] += 1
                    modified = True
                    logger.warning("Wrapped bare array in '%s': %s", role_name, short_name)

        if modified:
            updated_files[path] = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            updated_files[path] = content

    total = sum(metrics.values())
    if total:
        logger.info(
            "Sanitized visuals - config: %d, stubs: %d, pos: %d, structure: %d, wrapped: %d",
            metrics["configs_stripped"],
            metrics["stubs_dropped"],
            metrics["positions_injected"],
            metrics["structure_fixed"],
            metrics["projections_wrapped"],
        )

    return updated_files, metrics


def clamp_visual_bounds(
    files: dict[str, str],
    logger: logging.Logger,
) -> dict[str, str]:
    """Ensure page height accommodates all visuals on that page."""
    page_paths: dict[str, str] = {}
    visual_paths: dict[str, list[str]] = {}

    for path in files:
        if path.endswith("/page.json") and "/pages/" in path:
            parts = path.split("/")
            idx = parts.index("pages")
            if idx + 1 < len(parts):
                page_id = parts[idx + 1]
                page_paths[page_id] = path

        if path.endswith("/visual.json") and "/visuals/" in path and "/pages/" in path:
            parts = path.split("/")
            idx = parts.index("pages")
            if idx + 1 < len(parts):
                page_id = parts[idx + 1]
                visual_paths.setdefault(page_id, []).append(path)

    updated_files = dict(files)

    for page_id, page_path in page_paths.items():
        vis_paths = visual_paths.get(page_id, [])
        if not vis_paths:
            continue

        try:
            page_json = json.loads(updated_files[page_path])
        except (json.JSONDecodeError, ValueError, KeyError):
            continue

        max_bottom = 0
        for vp in vis_paths:
            try:
                vdata = json.loads(updated_files[vp])
                pos = vdata.get("position", {})
                y = pos.get("y", 0)
                h = pos.get("height", 0)
                max_bottom = max(max_bottom, y + h)
            except (json.JSONDecodeError, ValueError, KeyError):
                continue

        current_height = page_json.get("height", 720)
        if max_bottom > current_height:
            new_height = max(max_bottom, 720)
            logger.warning("Page '%s' height adjusted: %s -> %s", page_id, current_height, new_height)
            page_json["height"] = new_height
            updated_files[page_path] = json.dumps(page_json, indent=2, ensure_ascii=False)

    return updated_files


def ensure_pages_json(
    files: dict[str, str],
    workbook_name: str,
    logger: logging.Logger,
) -> dict[str, str]:
    """Generate pages/pages.json if the LLM did not emit one."""
    report_prefix = f"{workbook_name}.Report"
    pages_json_path = f"{report_prefix}/definition/pages/pages.json"

    if pages_json_path in files:
        logger.info("pages.json already present - skipping.")
        return files

    page_ids: list[str] = []
    for path in files:
        if path.endswith("/page.json") and "/pages/" in path:
            parts = path.split("/")
            idx = parts.index("pages")
            if idx + 1 < len(parts):
                page_ids.append(parts[idx + 1])

    page_ids.sort()

    if not page_ids:
        logger.warning("No pages found - cannot generate pages.json.")
        return files

    pages_json_content = json.dumps(
        {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/"
                "fabric/item/report/definition/pagesMetadata/"
                "1.0.0/schema.json"
            ),
            "pageOrder": page_ids,
            "activePageName": page_ids[0],
        },
        indent=2,
        ensure_ascii=False,
    )

    updated_files = dict(files)
    updated_files[pages_json_path] = pages_json_content
    logger.info("Generated pages.json with %d page(s).", len(page_ids))
    return updated_files


def build_field_index_from_tdd(
    tdd_sm: dict,
    tdd_dax: dict,
    tdd_report: dict,
) -> tuple[dict[str, str], set[str], set[str]]:
    """Build lookup structures for field reference correction from TDD."""
    measure_set: set[str] = set()
    for measure in tdd_dax.get("measures", []):
        owner = measure.get("owner_table", "")
        caption = measure.get("caption", "")
        if owner and caption:
            measure_set.add(f"{owner}.{caption}")

    column_set: set[str] = set()
    for table in tdd_sm.get("tables", []):
        table_name = table.get("name", "")
        for column in table.get("columns", []):
            col_name = column.get("name", "")
            if table_name and col_name:
                column_set.add(f"{table_name}.{col_name}")

    entity_resolution = tdd_report.get("entity_resolution", {})
    calc_mapping: dict[str, str] = entity_resolution.get("calculated_field_map", {})

    return calc_mapping, measure_set, column_set


def fix_field_references(
    files: dict[str, str],
    calc_mapping: dict[str, str],
    measure_set: set[str],
    column_set: set[str],
    logger: logging.Logger,
) -> tuple[dict[str, str], dict[str, int]]:
    """Deterministically correct field references in visual.json files."""
    updated_files: dict[str, str] = {}
    metrics: dict[str, int] = {
        "calc_names_resolved": 0,
        "field_kinds_fixed": 0,
    }

    field_kinds = ("Measure", "Column", "Aggregation")

    for path, content in files.items():
        if not (path.endswith("/visual.json") and "/visuals/" in path):
            updated_files[path] = content
            continue

        try:
            visual_data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            updated_files[path] = content
            continue

        modified = False
        query_state = visual_data.get("visual", {}).get("query", {}).get("queryState", {})

        for role_data in query_state.values():
            if not isinstance(role_data, dict):
                continue
            for proj in role_data.get("projections", []):
                field = proj.get("field", {})
                if not isinstance(field, dict):
                    continue

                kind: str | None = None
                inner: dict | None = None
                for field_kind in field_kinds:
                    if field_kind in field:
                        kind = field_kind
                        inner = field[field_kind]
                        break
                if kind is None or inner is None:
                    continue

                if kind == "Aggregation":
                    col_block = inner.get("Expression", {}).get("Column", {})
                    entity = col_block.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                    prop = col_block.get("Property", "")
                else:
                    entity = inner.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                    prop = inner.get("Property", "")

                if not entity or not prop:
                    continue

                new_prop = prop
                if prop.startswith("Calculation_") and prop in calc_mapping:
                    new_prop = calc_mapping[prop]
                    if kind == "Aggregation":
                        col_block = inner["Expression"]["Column"]
                        col_block["Property"] = new_prop
                    else:
                        inner["Property"] = new_prop
                    proj["queryRef"] = f"{entity}.{new_prop}"
                    if "nativeQueryRef" in proj:
                        proj["nativeQueryRef"] = new_prop
                    modified = True
                    metrics["calc_names_resolved"] += 1
                    logger.debug("Resolved %s -> %s in %s", prop, new_prop, path)

                if kind != "Aggregation":
                    qualified = f"{entity}.{new_prop}"
                    correct_kind = None
                    if qualified in measure_set:
                        correct_kind = "Measure"
                    elif qualified in column_set:
                        correct_kind = "Column"

                    if correct_kind and correct_kind != kind:
                        field[correct_kind] = field.pop(kind)
                        modified = True
                        metrics["field_kinds_fixed"] += 1
                        logger.debug("Fixed %s -> %s for %s in %s", kind, correct_kind, qualified, path)

        filters = visual_data.get("filterConfig", {}).get("filters", [])
        for filt in filters:
            filt_field = filt.get("field", {})
            if not isinstance(filt_field, dict):
                continue

            kind = None
            inner = None
            for field_kind in field_kinds:
                if field_kind in filt_field:
                    kind = field_kind
                    inner = filt_field[field_kind]
                    break
            if kind is None or inner is None:
                continue

            if kind == "Aggregation":
                col_block = inner.get("Expression", {}).get("Column", {})
                entity = col_block.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                prop = col_block.get("Property", "")
            else:
                entity = inner.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                prop = inner.get("Property", "")

            if not entity or not prop:
                continue

            new_prop = prop
            if prop.startswith("Calculation_") and prop in calc_mapping:
                new_prop = calc_mapping[prop]
                if kind == "Aggregation":
                    col_block = inner["Expression"]["Column"]
                    col_block["Property"] = new_prop
                else:
                    inner["Property"] = new_prop
                modified = True

            if kind != "Aggregation":
                qualified = f"{entity}.{new_prop}"
                correct_kind = None
                if qualified in measure_set:
                    correct_kind = "Measure"
                elif qualified in column_set:
                    correct_kind = "Column"

                if correct_kind and correct_kind != kind:
                    filt_field[correct_kind] = filt_field.pop(kind)
                    modified = True

        if modified:
            updated_files[path] = json.dumps(visual_data, indent=2, ensure_ascii=False)
        else:
            updated_files[path] = content

    if metrics["calc_names_resolved"]:
        logger.info("Resolved %d Calculation_XXX -> PBI name(s)", metrics["calc_names_resolved"])
    if metrics["field_kinds_fixed"]:
        logger.info("Fixed %d Column/Measure misattributions", metrics["field_kinds_fixed"])

    return updated_files, metrics
