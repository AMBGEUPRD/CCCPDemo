"""Input-format detection and metadata-extractor dispatch helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from zipfile import BadZipFile, ZipFile

from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.output_dirs import validate_name

SourceFormat = Literal["tableau", "pbip"]

TABLEAU_METADATA_AGENT = "tableau_metadata_extractor_agent"
POWERBI_METADATA_AGENT = "powerbi_metadata_extractor_agent"


@dataclass(frozen=True)
class DetectedSource:
    """Resolved source metadata for an uploaded/local input file."""

    source_format: SourceFormat
    workbook_name: str
    metadata_agent_name: str
    pbip_entry: str | None = None


@dataclass(frozen=True)
class DispatchedExtractionResult:
    """Return value for auto-dispatched metadata extraction."""

    source_format: SourceFormat
    workbook_name: str
    metadata_agent_name: str
    result_text: str


def detect_source_file(source_path: str | Path) -> DetectedSource:
    """Detect the supported source format from *source_path*.

    Detection is extension-led and content-validated:
    - ``.twb`` / ``.twbx`` => Tableau
    - ``.zip`` with exactly one ``.pbip`` => PBIP package
    """
    path = Path(source_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    ext = path.suffix.lower()
    if ext in {".twb", ".twbx"}:
        _validate_tableau_input(path)
        return DetectedSource(
            source_format="tableau",
            workbook_name=validate_name("Workbook name", path.stem),
            metadata_agent_name=TABLEAU_METADATA_AGENT,
        )

    if ext == ".zip":
        pbip_entry = _find_single_pbip_entry(path)
        workbook_name = validate_name("PBIP project name", Path(pbip_entry).stem)
        return DetectedSource(
            source_format="pbip",
            workbook_name=workbook_name,
            metadata_agent_name=POWERBI_METADATA_AGENT,
            pbip_entry=pbip_entry,
        )

    raise ValueError(
        f"Unsupported format '{path.suffix}'. Supported formats: .twb, .twbx, .zip (PBIP package)."
    )


def extract_metadata_with_dispatch(
    source_path: str | Path,
    *,
    settings: AgentSettings | None = None,
    reset_output: bool = True,
) -> DispatchedExtractionResult:
    """Detect *source_path*, run the matching extractor, and return its result."""
    detected = detect_source_file(source_path)
    if detected.source_format == "tableau":
        from Tableau2PowerBI.agents.metadata_extractor import TableauMetadataExtractorAgent

        agent = TableauMetadataExtractorAgent(settings=settings)
        result_text = agent.extract_tableau_metadata(str(source_path), reset_output=reset_output)
    else:
        from Tableau2PowerBI.agents.powerbi_metadata_extractor import PowerBIMetadataExtractorAgent

        agent = PowerBIMetadataExtractorAgent(settings=settings)
        result_text = agent.extract_powerbi_metadata(str(source_path), reset_output=reset_output)

    return DispatchedExtractionResult(
        source_format=detected.source_format,
        workbook_name=detected.workbook_name,
        metadata_agent_name=detected.metadata_agent_name,
        result_text=result_text,
    )


def _validate_tableau_input(path: Path) -> None:
    """Validate that *path* is a readable Tableau workbook/package."""
    from Tableau2PowerBI.agents.metadata_extractor.tableau_xml_parsing import load_tableau_workbook_root

    load_tableau_workbook_root(path)


def _find_single_pbip_entry(zip_path: Path) -> str:
    """Return the single ``.pbip`` entry path inside a PBIP ZIP package."""
    try:
        with ZipFile(zip_path, "r") as archive:
            pbip_files = sorted(
                name
                for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith(".pbip")
            )
    except BadZipFile as exc:
        raise ValueError(f"Invalid ZIP archive: {zip_path}") from exc

    if not pbip_files:
        raise ValueError("ZIP upload must contain exactly one .pbip file.")
    if len(pbip_files) > 1:
        listed = ", ".join(pbip_files)
        raise ValueError(f"ZIP upload contains multiple .pbip files: {listed}")
    return pbip_files[0]
