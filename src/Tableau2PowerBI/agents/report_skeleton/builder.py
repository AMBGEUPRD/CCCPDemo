"""Deterministic ReportSkeleton builder from TDD report data."""

from __future__ import annotations

import hashlib

from Tableau2PowerBI.agents.report_skeleton.report_skeleton import ReportSkeleton
from Tableau2PowerBI.agents.report_skeleton.skeleton_page import SkeletonPage
from Tableau2PowerBI.agents.report_skeleton.skeleton_visual import SkeletonVisual
from Tableau2PowerBI.agents.report_skeleton.visual_position import VisualPosition
from Tableau2PowerBI.core.models import MigrationWarning


def make_hex_id(name: str) -> str:
    """Generate a deterministic 20-char lowercase hex ID from a name."""
    return hashlib.md5(name.encode("utf-8")).hexdigest()[:20]


def build_skeleton_from_tdd(tdd_report: dict) -> ReportSkeleton:
    """Build a ReportSkeleton deterministically from TDD report data."""
    pages: list[SkeletonPage] = []
    warnings: list[MigrationWarning] = []

    for page_data in tdd_report.get("pages", []):
        dashboard_name = page_data.get("dashboard_name", "")
        display_name = page_data.get("display_name", dashboard_name)
        page_hex_id = make_hex_id(dashboard_name)
        width = page_data.get("width", 1280)
        height = max(page_data.get("height", 720), 720)

        visuals: list[SkeletonVisual] = []
        for idx, vis_data in enumerate(page_data.get("visuals", [])):
            ws_name = vis_data.get("worksheet_name", "")
            vtype = vis_data.get("visual_type", "barChart")
            pos = vis_data.get("position", {})
            visual_hex_id = make_hex_id(f"{dashboard_name}/{ws_name}")

            visuals.append(
                SkeletonVisual(
                    worksheet_name=ws_name,
                    visual_type=vtype,
                    hex_id=visual_hex_id,
                    position=VisualPosition(
                        x=pos.get("x", 0),
                        y=pos.get("y", 0),
                        width=pos.get("width", 400),
                        height=pos.get("height", 300),
                        tab_order=idx,
                    ),
                )
            )

        if visuals:
            max_bottom = max(v.position.y + v.position.height for v in visuals)
            if max_bottom > height:
                height = max_bottom

        pages.append(
            SkeletonPage(
                dashboard_name=dashboard_name,
                display_name=display_name,
                hex_id=page_hex_id,
                width=width,
                height=height,
                visuals=visuals,
            )
        )

    for ws_name in tdd_report.get("standalone_worksheets", []):
        pages.append(
            SkeletonPage(
                dashboard_name=ws_name,
                display_name=ws_name,
                hex_id=make_hex_id(ws_name),
                width=1280,
                height=720,
                visuals=[
                    SkeletonVisual(
                        worksheet_name=ws_name,
                        visual_type="tableEx",
                        hex_id=make_hex_id(f"{ws_name}/standalone"),
                        position=VisualPosition(
                            x=0,
                            y=0,
                            width=1280,
                            height=720,
                            tab_order=0,
                        ),
                    )
                ],
            )
        )

    return ReportSkeleton(pages=pages, warnings=warnings)
