"""Stage 1 — Power BI PBIP metadata extractor."""

from __future__ import annotations

import json
from pathlib import Path

from Tableau2PowerBI.agents.powerbi_metadata_extractor.pbip_parsing import extract_pbip_metadata
from Tableau2PowerBI.core.agent import DeterministicAgent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.output_dirs import (
    ensure_output_dir,
    get_output_dir,
    reset_output_dir,
    save_json_locally,
)


class PowerBIMetadataExtractorAgent(DeterministicAgent):
    """Extract structured metadata from zipped PBIP projects."""

    def __init__(self, settings: AgentSettings | None = None):
        super().__init__(
            skill_name="powerbi_metadata_extractor_agent",
            settings=settings,
        )

    def extract_powerbi_metadata(self, package_path: str, *, reset_output: bool = True) -> str:
        """Parse a zipped PBIP package and write metadata JSON to disk."""
        metadata = extract_pbip_metadata(package_path)
        workbook_name = Path(package_path).resolve().stem
        project_name = metadata.get("pbip", {}).get("project", {}).get("name") or workbook_name
        output_dir = get_output_dir(self.skill_name, project_name, self.settings)
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        self._save_metadata_json(output_dir, metadata)
        return json.dumps(metadata, indent=2, ensure_ascii=False)

    def _save_metadata_json(self, output_dir: Path, metadata: dict) -> None:
        output_path = output_dir / "powerbi_metadata.json"
        save_json_locally(metadata, str(output_path))
        self.logger.info("Parsed PBIP metadata saved successfully.")
