"""RunManifest dataclass — top-level manifest for a pipeline run."""

from __future__ import annotations

from dataclasses import dataclass, field

from Tableau2PowerBI.core.run_history.stage_record import StageRecord


@dataclass
class RunManifest:
    """Top-level manifest for a single pipeline run."""

    run_id: str
    workbook_name: str
    workbook_file: str
    created_at: str
    updated_at: str
    stages: dict[str, StageRecord] = field(default_factory=dict)
    stored_artifacts: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    adls_path: str | None = None
    result_id: str | None = None
    source_format: str = "tableau"
    metadata_agent_name: str = "tableau_metadata_extractor_agent"

    def to_dict(self) -> dict:
        """Serialise the full manifest to a JSON-friendly dict."""
        return {
            "run_id": self.run_id,
            "workbook_name": self.workbook_name,
            "workbook_file": self.workbook_file,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "stored_artifacts": self.stored_artifacts,
            "token_usage": self.token_usage,
            "adls_path": self.adls_path,
            "result_id": self.result_id,
            "source_format": self.source_format,
            "metadata_agent_name": self.metadata_agent_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RunManifest:
        """Deserialise from a JSON dict."""
        stages = {k: StageRecord.from_dict(v) for k, v in data.get("stages", {}).items()}
        return cls(
            run_id=data["run_id"],
            workbook_name=data["workbook_name"],
            workbook_file=data.get("workbook_file", ""),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            stages=stages,
            stored_artifacts=data.get("stored_artifacts", []),
            token_usage=data.get("token_usage", {}),
            adls_path=data.get("adls_path"),
            result_id=data.get("result_id"),
            source_format=data.get("source_format", "tableau"),
            metadata_agent_name=data.get("metadata_agent_name", "tableau_metadata_extractor_agent"),
        )
