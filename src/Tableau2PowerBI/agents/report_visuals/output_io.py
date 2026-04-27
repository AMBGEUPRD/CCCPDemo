"""Output validation and persistence helpers for report visuals generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from Tableau2PowerBI.core.models import MigrationWarning

_REQUIRED_RELATIVE_PATHS = {
    ".platform",
    "definition.pbir",
    ".pbi/localSettings.json",
    "definition/report.json",
    "definition/version.json",
    "definition/pages/pages.json",
}


def validate_completeness(
    files: dict[str, str],
    workbook_name: str,
    logger,
) -> None:
    """Log warnings when required PBIR files/pages/visuals are missing."""
    first_key = next(iter(files))
    prefix_end = first_key.find("/")
    report_prefix = first_key[: prefix_end + 1] if prefix_end != -1 else ""

    present_relative = {key[len(report_prefix) :] for key in files if key.startswith(report_prefix)}

    for required in sorted(_REQUIRED_RELATIVE_PATHS):
        if required not in present_relative:
            logger.warning(
                "Required PBIR file missing: %s%s",
                report_prefix,
                required,
            )

    pages = [p for p in present_relative if p.startswith("definition/pages/")]
    if not pages:
        logger.warning(
            "No pages found for workbook '%s'",
            workbook_name,
        )

    visuals = [p for p in present_relative if "/visuals/" in p]
    if not visuals:
        logger.warning(
            "No visuals found for workbook '%s'",
            workbook_name,
        )

    page_count = len({p.split("/")[2] for p in pages if len(p.split("/")) > 2})
    logger.info(
        "File inventory - pages: %d, visuals: %d, total: %d",
        page_count,
        len(visuals),
        len(present_relative),
    )


def save_decisions(
    files: dict[str, str],
    warnings: list[MigrationWarning],
    output_dir: Path,
    logger,
) -> None:
    """Write report files and warnings.json from validated decisions."""
    page_count = 0
    visual_count = 0

    for file_path, content in files.items():
        output_file = output_dir / file_path
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(content, encoding="utf-8")

        if "/visuals/" in file_path and file_path.endswith("/visual.json"):
            visual_count += 1
        elif "/pages/" in file_path and file_path.endswith("/page.json"):
            page_count += 1

    logger.info(
        "File inventory - pages: %d, visuals: %d, total: %d",
        page_count,
        visual_count,
        len(files),
    )

    if warnings:
        logger.warning(
            "Agent emitted %d migration warning(s):",
            len(warnings),
        )
        for warning in warnings:
            logger.warning(
                "  [%s] %s - %s",
                warning.severity,
                warning.code,
                warning.message,
            )
    else:
        logger.info("No migration warnings emitted.")

    warnings_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warning_count": len(warnings),
        "warnings": [warning.model_dump() for warning in warnings],
    }
    warnings_path = output_dir / "warnings.json"
    warnings_path.write_text(
        json.dumps(warnings_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved warnings.json")
