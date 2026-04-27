"""StageRecord dataclass — per-stage metadata within a run manifest."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from Tableau2PowerBI.core.run_history.stage_status import StageStatus


@dataclass
class StageRecord:
    """Per-stage metadata within a run manifest."""

    status: StageStatus = StageStatus.NOT_STARTED
    deterministic: bool = True
    started_at: str | None = None
    completed_at: str | None = None
    input_hash: str | None = None
    duration_seconds: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict:
        """Serialise to a JSON-friendly dict."""
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> StageRecord:
        """Deserialise from a JSON dict."""
        data = dict(data)
        raw = data.pop("status", "not_started")
        status = StageStatus(raw)
        return cls(status=status, **data)
