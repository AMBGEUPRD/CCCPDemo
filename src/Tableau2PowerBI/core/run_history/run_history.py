"""RunHistory — persistent run manifest management on the local filesystem."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from Tableau2PowerBI.core.run_history.run_manifest import RunManifest
from Tableau2PowerBI.core.run_history.stage_record import StageRecord
from Tableau2PowerBI.core.run_history.stage_status import StageStatus

logger = logging.getLogger(__name__)

# Agents whose outputs are stored per-run for restore capability.
# extracted_data/ is excluded — large and derived from the original .twbx.
_STORABLE_AGENTS: tuple[str, ...] = (
    "tableau_metadata_extractor_agent",
    "tableau_functional_doc_agent",
    "target_technical_doc_agent",
    "pbip_project_skeleton_agent",
    "pbip_semantic_model_generator_agent",
    "tmdl_measures_generator_agent",
    "pbir_report_generator_agent",
    "pbip_project_assembler_agent",
)

# Subdirectories to skip when copying artefacts into the run folder.
_SKIP_SUBDIRS: frozenset[str] = frozenset({"extracted_data"})


def _utcnow_iso() -> str:
    """Return an ISO 8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunHistory:
    """Manage persistent run manifests on the local filesystem.

    Run folder layout::

        {runs_root}/{workbook_name}/{run_id}/manifest.json
    """

    def __init__(
        self,
        runs_root: Path,
        output_root: Path,
        max_runs_per_workbook: int = 10,
    ) -> None:
        self._runs_root = Path(runs_root)
        self._output_root = Path(output_root)
        self._max_runs = max_runs_per_workbook

    # ── CRUD ──────────────────────────────────────────────────────────

    def create_run(self, workbook_name: str, workbook_file: str) -> RunManifest:
        """Create a new run manifest and persist it to disk."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
        run_id = ts
        now = _utcnow_iso()
        manifest = RunManifest(
            run_id=run_id,
            workbook_name=workbook_name,
            workbook_file=workbook_file,
            created_at=now,
            updated_at=now,
        )
        self.save_run(manifest)
        logger.info("Created run %s for '%s'", run_id, workbook_name)
        return manifest

    def save_run(self, manifest: RunManifest) -> None:
        """Atomically write the manifest to disk."""
        manifest.updated_at = _utcnow_iso()
        run_dir = self._run_dir(manifest.workbook_name, manifest.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / "manifest.json"
        data = json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False)
        fd, tmp = tempfile.mkstemp(dir=str(run_dir), suffix=".tmp")
        try:
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            fd = -1
            os.replace(tmp, str(target))
        except BaseException:
            if fd != -1:
                os.close(fd)
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def load_run(self, workbook_name: str, run_id: str) -> RunManifest:
        """Load a run manifest from disk."""
        path = self._run_dir(workbook_name, run_id) / "manifest.json"
        if not path.exists():
            raise FileNotFoundError(f"Run manifest not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return RunManifest.from_dict(data)

    def get_latest_run(self, workbook_name: str) -> RunManifest | None:
        """Return the most recent run for a workbook, or ``None``."""
        runs = self.list_runs(workbook_name)
        return runs[0] if runs else None

    def list_runs(self, workbook_name: str) -> list[RunManifest]:
        """Return all runs for a workbook, sorted newest-first."""
        wb_dir = self._runs_root / workbook_name
        if not wb_dir.is_dir():
            return []
        manifests: list[RunManifest] = []
        for child in sorted(wb_dir.iterdir(), reverse=True):
            mf = child / "manifest.json"
            if mf.is_file():
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    manifests.append(RunManifest.from_dict(data))
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Skipping corrupt manifest %s: %s", mf, exc)
        return manifests

    def list_workbooks(self) -> list[str]:
        """Return workbook names that have at least one run."""
        if not self._runs_root.is_dir():
            return []
        return sorted(
            d.name for d in self._runs_root.iterdir() if d.is_dir() and any(sub.is_dir() for sub in d.iterdir())
        )

    # ── Stage updates ─────────────────────────────────────────────────

    def update_stage(
        self,
        manifest: RunManifest,
        stage_name: str,
        *,
        status: StageStatus,
        input_hash: str | None = None,
        duration_seconds: float | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        deterministic: bool = True,
    ) -> RunManifest:
        """Update a stage record and persist the manifest."""
        now = _utcnow_iso()
        record = manifest.stages.get(stage_name, StageRecord(deterministic=deterministic))
        record.status = status
        record.input_hash = input_hash or record.input_hash
        record.deterministic = deterministic
        record.input_tokens = input_tokens
        record.output_tokens = output_tokens

        if status == StageStatus.COMPLETED:
            record.completed_at = now
            record.duration_seconds = duration_seconds
        elif status == StageStatus.FAILED:
            record.completed_at = now
            record.duration_seconds = duration_seconds
        elif status in (StageStatus.NOT_STARTED,):
            record.started_at = now

        manifest.stages[stage_name] = record
        self.save_run(manifest)
        return manifest

    def mark_overwritten(self, workbook_name: str, stage_names: set[str], exclude_run_id: str) -> None:
        """Mark stages on older runs as ``overwritten``."""
        for run in self.list_runs(workbook_name):
            if run.run_id == exclude_run_id:
                continue
            changed = False
            for stage_name in stage_names:
                record = run.stages.get(stage_name)
                if record and record.status == StageStatus.COMPLETED:
                    record.status = StageStatus.OVERWRITTEN
                    changed = True
            if changed:
                self.save_run(run)

    # ── Artefact storage & restore ────────────────────────────────────

    def store_artifacts(self, manifest: RunManifest, agent_name: str) -> None:
        """Copy agent outputs into the run folder for later restore."""
        if agent_name not in _STORABLE_AGENTS:
            logger.debug("Agent '%s' not in storable list — skip", agent_name)
            return

        src = self._output_root / agent_name / manifest.workbook_name
        if not src.is_dir():
            logger.warning("Source dir missing for store_artifacts: %s", src)
            return

        dst = self._run_dir(manifest.workbook_name, manifest.run_id) / agent_name
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True, exist_ok=True)

        for item in src.iterdir():
            if item.name in _SKIP_SUBDIRS:
                continue
            target = dst / item.name
            if item.is_file():
                shutil.copy2(item, target)
            elif item.is_dir():
                shutil.copytree(item, target)

        rel = str(Path(agent_name))
        if rel not in manifest.stored_artifacts:
            manifest.stored_artifacts.append(rel)
        self.save_run(manifest)
        logger.info("Stored artefacts: %s → run %s", agent_name, manifest.run_id)

    def restore_run(self, manifest: RunManifest) -> None:
        """Copy stored per-run artefacts back into ``data/output/``."""
        run_dir = self._run_dir(manifest.workbook_name, manifest.run_id)
        for agent_name in manifest.stored_artifacts:
            src = run_dir / agent_name
            if not src.is_dir():
                logger.warning("Stored artefact dir missing: %s", src)
                continue
            dst = self._output_root / agent_name / manifest.workbook_name
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                target = dst / item.name
                if item.is_file():
                    shutil.copy2(item, target)
                elif item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
        logger.info("Restored artefacts for run %s → data/output/", manifest.run_id)

    # ── Cleanup ───────────────────────────────────────────────────────

    def cleanup_old_runs(self, workbook_name: str) -> None:
        """Keep only the newest ``max_runs_per_workbook`` runs."""
        runs = self.list_runs(workbook_name)
        if len(runs) <= self._max_runs:
            return
        for old_run in runs[self._max_runs :]:
            run_dir = self._run_dir(workbook_name, old_run.run_id)
            if run_dir.exists():
                shutil.rmtree(run_dir)
                logger.info("Cleaned up old run: %s/%s", workbook_name, old_run.run_id)

    # ── Internals ─────────────────────────────────────────────────────

    def _run_dir(self, workbook_name: str, run_id: str) -> Path:
        """Return the filesystem path for a specific run."""
        return self._runs_root / workbook_name / run_id
