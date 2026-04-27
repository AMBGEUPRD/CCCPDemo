"""Orchestration and static file helpers for PBIR report generation."""

from __future__ import annotations

import hashlib
import json

from Tableau2PowerBI.agents.report_page_visuals import PageVisualsOutput
from Tableau2PowerBI.agents.report_skeleton import (
    ReportSkeleton,
    SkeletonPage,
)
from Tableau2PowerBI.agents.report_skeleton.builder import build_skeleton_from_tdd as _build_skeleton_from_tdd
from Tableau2PowerBI.core.models import MigrationWarning


def build_skeleton_from_tdd(tdd_report: dict) -> ReportSkeleton:
    """Backward-compatible shim to deterministic report skeleton builder."""
    return _build_skeleton_from_tdd(tdd_report)


def filter_metadata_for_page(report_input: dict, skeleton_page: SkeletonPage) -> str:
    """Filter report metadata to only visuals on this page."""
    page_worksheet_names = {v.worksheet_name for v in skeleton_page.visuals}

    visuals: list[dict] = []
    for page in report_input.get("pages", []):
        for visual in page.get("visuals", []):
            if visual.get("worksheet_name") in page_worksheet_names:
                visuals.append(visual)

    if visuals:
        filtered: dict = {
            "visuals": visuals,
            "entity_resolution": report_input.get("entity_resolution", {}),
        }
    else:
        filtered_worksheets = [
            ws for ws in report_input.get("worksheets", []) if ws.get("name") in page_worksheet_names
        ]
        filtered = {
            "datasource_index": report_input.get("datasource_index", {}),
            "worksheets": filtered_worksheets,
        }

    return json.dumps(filtered, separators=(",", ":"), ensure_ascii=False)


def assemble_report(
    skeleton: ReportSkeleton,
    page_visuals: dict[str, PageVisualsOutput],
    workbook_name: str,
    static_files: dict[str, str],
) -> tuple[dict[str, str], list[MigrationWarning]]:
    """Assemble report files from skeleton + page visuals."""
    prefix = f"{workbook_name}.Report"
    files = dict(static_files)
    all_warnings: list[MigrationWarning] = list(skeleton.warnings)

    for page in skeleton.pages:
        page_output = page_visuals.get(page.hex_id)
        if page_output is None:
            continue

        for visual_hex_id, content in page_output.visuals.items():
            path = f"{prefix}/definition/pages/{page.hex_id}/visuals/{visual_hex_id}/visual.json"
            files[path] = content

        all_warnings.extend(page_output.warnings)

    return files, all_warnings


def generate_static_files(skeleton: ReportSkeleton, workbook_name: str) -> dict[str, str]:
    """Generate deterministic PBIR boilerplate files."""
    prefix = f"{workbook_name}.Report"
    files: dict[str, str] = {}

    logical_id = hashlib.md5(workbook_name.encode("utf-8")).hexdigest()
    logical_id = f"{logical_id[:8]}-{logical_id[8:12]}-{logical_id[12:16]}-{logical_id[16:20]}-{logical_id[20:32]}"
    files[f"{prefix}/.platform"] = json.dumps(
        {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/"
                "fabric/gitIntegration/platformProperties/"
                "2.0.0/schema.json"
            ),
            "metadata": {"type": "Report", "displayName": workbook_name},
            "config": {"version": "2.0", "logicalId": logical_id},
        },
        indent=2,
        ensure_ascii=False,
    )

    files[f"{prefix}/definition.pbir"] = json.dumps(
        {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/"
                "fabric/item/report/definitionProperties/"
                "2.0.0/schema.json"
            ),
            "version": "4.0",
            "datasetReference": {"byPath": {"path": f"../{workbook_name}.SemanticModel"}},
        },
        indent=2,
        ensure_ascii=False,
    )

    files[f"{prefix}/.pbi/localSettings.json"] = json.dumps(
        {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/" "fabric/item/report/localSettings/" "1.0.0/schema.json"
            ),
        },
        indent=2,
        ensure_ascii=False,
    )

    files[f"{prefix}/definition/version.json"] = json.dumps(
        {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/"
                "fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
            ),
            "version": "2.0.0",
        },
        indent=2,
        ensure_ascii=False,
    )

    files[f"{prefix}/definition/report.json"] = json.dumps(
        {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/" "fabric/item/report/definition/report/3.2.0/schema.json"
            ),
            "themeCollection": {
                "baseTheme": {
                    "name": "CY26SU02",
                    "reportVersionAtImport": {
                        "visual": "2.6.0",
                        "report": "3.1.0",
                        "page": "2.3.0",
                    },
                    "type": "SharedResources",
                }
            },
            "resourcePackages": [
                {
                    "name": "SharedResources",
                    "type": "SharedResources",
                    "items": [
                        {
                            "name": "CY26SU02",
                            "path": "BaseThemes/CY26SU02.json",
                            "type": "BaseTheme",
                        }
                    ],
                }
            ],
            "settings": {
                "useStylableVisualContainerHeader": True,
                "exportDataMode": "AllowSummarized",
                "defaultDrillFilterOtherVisuals": True,
                "allowChangeFilterTypes": True,
                "useEnhancedTooltips": True,
                "useDefaultAggregateDisplayName": True,
            },
        },
        indent=2,
        ensure_ascii=False,
    )

    page_ids = [p.hex_id for p in skeleton.pages]
    files[f"{prefix}/definition/pages/pages.json"] = json.dumps(
        {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/"
                "fabric/item/report/definition/pagesMetadata/1.0.0/schema.json"
            ),
            "pageOrder": page_ids,
            "activePageName": page_ids[0] if page_ids else "",
        },
        indent=2,
        ensure_ascii=False,
    )

    for page in skeleton.pages:
        page_path = f"{prefix}/definition/pages/{page.hex_id}/page.json"
        files[page_path] = json.dumps(
            {
                "$schema": (
                    "https://developer.microsoft.com/json-schemas/"
                    "fabric/item/report/definition/page/2.1.0/schema.json"
                ),
                "name": page.hex_id,
                "displayName": page.display_name,
                "width": page.width,
                "height": page.height,
                "displayOption": "FitToPage",
            },
            indent=2,
            ensure_ascii=False,
        )

        bookmark_path = f"{prefix}/definition/bookmarks/bookmark_{page.hex_id}.json"
        files[bookmark_path] = json.dumps(
            {
                "id": f"bookmark_{page.hex_id}",
                "displayName": page.display_name,
                "explorationState": {"sections": {page.hex_id: {"defaultSection": True}}},
            },
            indent=2,
            ensure_ascii=False,
        )

    return files
