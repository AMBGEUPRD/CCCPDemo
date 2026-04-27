"""StageStatus enum — lifecycle status for a pipeline stage."""

from __future__ import annotations

from enum import Enum


class StageStatus(str, Enum):
    """Lifecycle status of a pipeline stage within a run."""

    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    FAILED = "failed"
    OVERWRITTEN = "overwritten"
