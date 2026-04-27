"""Capture golden inputs from sample workbooks.

Runs Stage 1 (deterministic metadata extraction) on each sample workbook
in ``data/input/`` and saves the downstream payloads to ``data/golden/<workbook>/``.

Usage::

    python -m tests.evals.capture_golden_inputs

This overwrites any existing golden files.  Commit the result to track
changes in extraction behaviour over time.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Ensure the src/ directory is importable when running as a standalone script.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from Tableau2PowerBI.agents.metadata_extractor.downstream_payloads import (  # noqa: E402
    DownstreamPayloadBuilder,
)
from Tableau2PowerBI.agents.metadata_extractor.tableau_xml_parsing import (  # noqa: E402
    extract_data_files_from_twbx,
    resolve_connection_paths,
)
from Tableau2PowerBI.agents.metadata_extractor.metadata_extractor import read_twb_file  # noqa: E402
from Tableau2PowerBI.core.logging_setup import setup_logging  # noqa: E402

logger = logging.getLogger(__name__)

SAMPLE_DIR = _PROJECT_ROOT / "data" / "input"
GOLDEN_DIR = _PROJECT_ROOT / "data" / "golden"

# Sample workbooks to capture.
_WORKBOOKS = list(SAMPLE_DIR.glob("*.twb")) + list(SAMPLE_DIR.glob("*.twbx"))


def capture_workbook(workbook_path: Path) -> None:
    """Run Stage 1 extraction and save golden sub-JSONs for one workbook."""
    name = workbook_path.stem
    out_dir = GOLDEN_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Capturing golden inputs for: %s", name)

    # Parse the workbook XML
    twb_content = read_twb_file(str(workbook_path))
    metadata = json.loads(twb_content)

    # For .twbx, extract data files to resolve connection paths.
    # We don't persist the data files in golden — just the metadata.
    if workbook_path.suffix.lower() == ".twbx":
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            file_mapping = extract_data_files_from_twbx(workbook_path, Path(tmpdir))
            metadata = resolve_connection_paths(metadata, file_mapping)

    # Build and save downstream payloads
    builder = DownstreamPayloadBuilder(metadata)
    written = builder.build_all_payload_files(out_dir)

    # Also save the full metadata for reference
    full_path = out_dir / "tableau_metadata.json"
    full_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    for payload_name, file_path in written.items():
        size_kb = file_path.stat().st_size / 1024
        logger.info("  %s.json (%.1f KB)", payload_name, size_kb)

    logger.info("Golden inputs saved to: %s", out_dir)


def main() -> None:
    """Capture golden inputs for all sample workbooks."""
    setup_logging()

    if not _WORKBOOKS:
        logger.error("No .twb/.twbx files found in %s", SAMPLE_DIR)
        sys.exit(1)

    logger.info("Found %d sample workbook(s)", len(_WORKBOOKS))

    for wb_path in sorted(_WORKBOOKS):
        try:
            capture_workbook(wb_path)
        except Exception:
            logger.exception("Failed to capture: %s", wb_path.name)

    logger.info("Done. Golden inputs are in: %s", GOLDEN_DIR)


if __name__ == "__main__":
    main()
