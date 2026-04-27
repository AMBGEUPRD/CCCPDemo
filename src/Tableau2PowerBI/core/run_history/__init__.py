"""Run history package — persistent run manifests, stage tracking, and cache logic.

Submodules
----------
run_history.py   :class:`RunHistory` — CRUD for run manifests on disk.
run_manifest.py  :class:`RunManifest` — top-level manifest dataclass.
stage_record.py  :class:`StageRecord` — per-stage execution record.
stage_status.py  :class:`StageStatus` — stage lifecycle enum.
stage_cache.py   ``STAGE_GRAPH``, :class:`StageInfo`, :class:`SkipDecision`,
                 input hashing, skip decisions, and ``resolve_stages_to_run()``.
"""

from Tableau2PowerBI.core.run_history.run_history import RunHistory
from Tableau2PowerBI.core.run_history.run_manifest import RunManifest
from Tableau2PowerBI.core.run_history.stage_cache import (
    STAGE_GRAPH,
    SkipDecision,
    StageInfo,
    compute_input_hash,
    get_stale_downstream,
    resolve_stages_to_run,
    should_skip_stage,
)
from Tableau2PowerBI.core.run_history.stage_record import StageRecord
from Tableau2PowerBI.core.run_history.stage_status import StageStatus

__all__ = [
    "RunHistory",
    "RunManifest",
    "StageRecord",
    "StageStatus",
    "STAGE_GRAPH",
    "SkipDecision",
    "StageInfo",
    "compute_input_hash",
    "get_stale_downstream",
    "resolve_stages_to_run",
    "should_skip_stage",
]
