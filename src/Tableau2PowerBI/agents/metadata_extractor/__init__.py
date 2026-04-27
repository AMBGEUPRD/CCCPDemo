"""Stage 1 — Tableau Metadata Extractor Agent.

Parses a ``.twb`` or ``.twbx`` Tableau workbook and produces:

1. ``tableau_metadata.json`` — the full raw extraction (audit trail)
2. Sub-JSON files for each downstream agent (semantic model, report, etc.)

For ``.twbx`` archives, data files (Excel, CSV) are extracted to an
``extracted_data/`` subdirectory and connection paths are resolved so
downstream stages can reference them with correct relative paths.

This stage is entirely deterministic — it does **not** call the LLM.
"""

import json
from pathlib import Path

from Tableau2PowerBI.agents.metadata_extractor.downstream_payloads import (
    DownstreamPayloadBuilder,
)
from Tableau2PowerBI.agents.metadata_extractor.tableau_xml_parsing import (
    extract_data_files_from_twbx,
    resolve_connection_paths,
)
from Tableau2PowerBI.agents.metadata_extractor.metadata_extractor import (
    read_twb_file,
)
from Tableau2PowerBI.core.agent import DeterministicAgent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.llm_output_parsing import extract_json_from_markdown
from Tableau2PowerBI.core.output_dirs import (
    ensure_output_dir,
    get_output_dir,
    reset_output_dir,
    save_json_locally,
)

# Subdirectory under the extractor output where embedded data files are placed.
# This is later read by the assembler agent to copy files next to the .pbip.
_EXTRACTED_DATA_DIR = "extracted_data"


class TableauMetadataExtractorAgent(DeterministicAgent):
    """Extract structured metadata from Tableau workbooks.

    This stage does not call the LLM.
    It inherits from :class:`DeterministicAgent` to share settings,
    logging, and skill metadata conventions with LLM stages.
    """

    def __init__(self, settings: AgentSettings | None = None):
        super().__init__(
            skill_name="tableau_metadata_extractor_agent",
            settings=settings,
        )

    def extract_tableau_metadata(self, twb_path: str, *, reset_output: bool = True) -> str:
        """Parse a Tableau workbook and write metadata + sub-JSONs to disk.

        Args:
            twb_path: Path to a ``.twb`` or ``.twbx`` file.

        Returns:
            The raw metadata as a JSON string.
        """
        # Step 1: Parse the workbook XML into a JSON string
        twb_content = read_twb_file(twb_path)
        self.logger.info("TWB file read successfully.")

        # Step 2: Prepare the output directory
        path = Path(twb_path).resolve()
        workbook_name = path.stem
        output_dir = get_output_dir(self.skill_name, workbook_name, self.settings)
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        # Step 3: For .twbx archives, extract embedded data files (Excel, CSV)
        # and build a mapping of archive-internal paths → absolute disk paths.
        file_mapping: dict[str, Path] = {}
        if path.suffix.lower() == ".twbx":
            extracted_dir = output_dir / _EXTRACTED_DATA_DIR
            file_mapping = extract_data_files_from_twbx(path, extracted_dir)
            self.logger.info(
                "Extracted %d data file(s) from TWBX",
                len(file_mapping),
            )

        # Step 4: Save the full raw metadata JSON (audit trail)
        self.save_response_as_json(workbook_name, twb_content)

        # Step 5: Enrich connection metadata with resolved file paths.
        # This adds 'resolved_filename' and 'relative_path' to each
        # file-based datasource connection so downstream agents know
        # where data files live.
        metadata = json.loads(twb_content)
        metadata = resolve_connection_paths(metadata, file_mapping)

        # Step 6: Decompose metadata into focused sub-JSONs for each
        # downstream agent (semantic model, report, connections, parameters).
        payload_builder = DownstreamPayloadBuilder(metadata)
        written = payload_builder.build_all_payload_files(output_dir)
        for name, file_path in written.items():
            size_kb = file_path.stat().st_size / 1024
            self.logger.info("Sub-JSON saved: %s.json (%.1f KB)", name, size_kb)

        return twb_content

    def save_response_as_json(self, workbook_name: str, response: str) -> None:
        """Save the raw extraction result as ``tableau_metadata.json``.

        This file is kept for audit/debugging purposes — the downstream
        agents consume the smaller sub-JSON files instead.
        """
        parsed_json = extract_json_from_markdown(response)
        output_path = get_output_dir(self.skill_name, workbook_name, self.settings) / "tableau_metadata.json"
        save_json_locally(parsed_json, str(output_path))
        self.logger.info("Parsed JSON saved successfully.")
