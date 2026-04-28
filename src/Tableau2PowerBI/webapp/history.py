"""Run history API endpoints.

Provides a FastAPI ``APIRouter`` for browsing, restoring, and
deleting pipeline run history.  Mounted on ``/api/history`` in
:mod:`Tableau2PowerBI.webapp.app`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from Tableau2PowerBI.core.config import get_agent_settings
from Tableau2PowerBI.core.run_history import STAGE_GRAPH, RunHistory, RunManifest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/history", tags=["history"])

_TOTAL_STAGES = len(STAGE_GRAPH)

# ── Safe-ID validation ────────────────────────────────────────────────
_SAFE_NAME = re.compile(r"^[\w\- .()]+$")


def _validate_name(value: str, label: str) -> str:
    """Raise HTTP 400 if value contains path-traversal characters."""
    if not value or not _SAFE_NAME.fullmatch(value):
        raise HTTPException(400, f"Invalid {label}: {value!r}")
    return value


def _get_history() -> RunHistory:
    """Build a ``RunHistory`` instance from current settings."""
    settings = get_agent_settings()
    return RunHistory(
        runs_root=settings.runs_root,
        output_root=settings.output_root,
        max_runs_per_workbook=settings.max_runs_per_workbook,
    )


# ── Endpoints ─────────────────────────────────────────────────────────


@router.get("")
async def list_workbooks() -> JSONResponse:
    """Return workbook names with their latest run summary."""
    history = _get_history()
    workbooks = history.list_workbooks()
    items = []
    for wb in workbooks:
        latest = history.get_latest_run(wb)
        if latest:
            stages_dict = {k: v.status.value for k, v in latest.stages.items()}
            completed = sum(1 for v in stages_dict.values() if v == "completed")
            failed = any(v == "failed" for v in stages_dict.values())
            status = "failed" if failed else ("complete" if completed >= _TOTAL_STAGES else "in_progress")
            items.append(
                {
                    "workbook_name": wb,
                    "latest_run_id": latest.run_id,
                    "created_at": latest.created_at,
                    "updated_at": latest.updated_at,
                    "stages": stages_dict,
                    "completion_pct": round(completed / _TOTAL_STAGES * 100),
                    "total_runs": len(history.list_runs(wb)),
                    "latest_status": status,
                }
            )
    return JSONResponse(content=items)


@router.get("/{workbook_name}")
async def list_runs(workbook_name: str) -> JSONResponse:
    """Return all runs for a workbook, newest-first."""
    workbook_name = _validate_name(workbook_name, "workbook_name")
    history = _get_history()
    runs = history.list_runs(workbook_name)
    return JSONResponse(content=[_enrich_run(r) for r in runs])


@router.get("/{workbook_name}/{run_id}")
async def get_run(workbook_name: str, run_id: str) -> JSONResponse:
    """Return the full manifest for a specific run."""
    workbook_name = _validate_name(workbook_name, "workbook_name")
    run_id = _validate_name(run_id, "run_id")
    history = _get_history()
    try:
        manifest = history.load_run(workbook_name, run_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Run not found: {workbook_name}/{run_id}")
    return JSONResponse(content=manifest.to_dict())


@router.post("/{workbook_name}/{run_id}/restore")
async def restore_run(workbook_name: str, run_id: str) -> JSONResponse:
    """Restore a previous run: copy artefacts back to ``data/output/``.

    Creates a fresh ``result_id`` and populates the in-memory result
    store so the frontend can navigate via ``?id={result_id}``.
    """
    workbook_name = _validate_name(workbook_name, "workbook_name")
    run_id = _validate_name(run_id, "run_id")
    history = _get_history()
    try:
        manifest = history.load_run(workbook_name, run_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Run not found: {workbook_name}/{run_id}")

    # Restore files into data/output/ without blocking the event loop.
    await asyncio.to_thread(history.restore_run, manifest)

    # Build a result payload matching what /analyze-stream produces
    result_id = f"result_{uuid.uuid4().hex[:12]}"

    # Try reading the stored extraction result for the result payload
    analysis_result = _load_stored_analysis(history, manifest)

    payload = json.dumps(
        {
            "id": result_id,
            "filename": manifest.workbook_file,
            "adls_path": manifest.adls_path,
            "result": analysis_result,
            "run_id": manifest.run_id,
            "timestamp": manifest.created_at,
            "restored": True,
        },
        ensure_ascii=False,
    )

    # Populate the in-memory result store (import from app)
    from Tableau2PowerBI.webapp.app import store_result

    store_result(result_id, payload)

    # Update manifest with new result_id cross-reference
    manifest.result_id = result_id
    history.save_run(manifest)

    # Suggest redirect based on pipeline progress
    completed_stages = {k for k, v in manifest.stages.items() if v.status.value == "completed"}
    if "target_technical_doc" in completed_stages:
        redirect_to = f"/project/{workbook_name}"
    else:
        redirect_to = f"/results?id={result_id}"

    logger.info(
        "Restored run %s → result_id=%s",
        run_id,
        result_id,
    )
    return JSONResponse(
        content={
            "result_id": result_id,
            "run_id": manifest.run_id,
            "workbook_name": workbook_name,
            "adls_path": manifest.adls_path,
            "redirect_to": redirect_to,
        }
    )


@router.delete("/{workbook_name}/{run_id}")
async def delete_run(workbook_name: str, run_id: str) -> JSONResponse:
    """Delete a specific run folder and its manifest."""
    workbook_name = _validate_name(workbook_name, "workbook_name")
    run_id = _validate_name(run_id, "run_id")
    settings = get_agent_settings()
    run_dir = settings.runs_root / workbook_name / run_id
    if not run_dir.is_dir():
        raise HTTPException(404, f"Run not found: {workbook_name}/{run_id}")
    await asyncio.to_thread(shutil.rmtree, run_dir)
    logger.info("Deleted run %s/%s", workbook_name, run_id)
    return JSONResponse(content={"status": "deleted"})


# ── Helpers ───────────────────────────────────────────────────────────


def _load_stored_analysis(
    history: RunHistory,
    manifest: RunManifest,
) -> str | None:
    """Try to read the analysis result JSON from the run snapshot.

    Reads directly from the per-run snapshot folder (inside
    ``data/runs/``) so that concurrent restores for the same workbook
    cannot overwrite each other's data in ``data/output/``.

    Falls back to the shared ``data/output/`` path for runs that were
    created before snapshot storage was introduced.  Within each source
    directory, ``analysis_result.json`` is preferred over the older
    ``tableau_metadata.json`` fall-back.
    """
    settings = get_agent_settings()

    # Primary: run-specific snapshot (race-free for concurrent restores).
    run_snapshot = settings.runs_root / manifest.workbook_name / manifest.run_id / "tableau_metadata_extractor_agent"
    for fname in ("analysis_result.json", "tableau_metadata.json"):
        candidate = run_snapshot / fname
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8")
            except Exception:
                logger.debug("Could not read snapshot %s", candidate, exc_info=True)

    # Fallback: shared output dir (pre-snapshot runs or missing snapshot).
    base = settings.output_root / "tableau_metadata_extractor_agent" / manifest.workbook_name
    for fname in ("analysis_result.json", "tableau_metadata.json"):
        candidate = base / fname
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8")
            except Exception:
                logger.debug("Could not read output %s", candidate, exc_info=True)

    return None


def _enrich_run(manifest: RunManifest) -> dict:
    """Build an enriched run dict with stages_full and completion info."""
    stages_full: dict[str, dict] = {}
    for stage_name, info in STAGE_GRAPH.items():
        record = manifest.stages.get(stage_name)
        if record:
            stages_full[stage_name] = {
                "status": record.status.value,
                "deterministic": info.deterministic,
                "upstream": list(info.upstream),
                "duration_seconds": record.duration_seconds,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
            }
        else:
            stages_full[stage_name] = {
                "status": "not_attempted",
                "deterministic": info.deterministic,
                "upstream": list(info.upstream),
                "duration_seconds": None,
                "input_tokens": None,
                "output_tokens": None,
            }

    completed = sum(1 for v in stages_full.values() if v["status"] == "completed")
    has_assembler = (
        "pbip_project_assembler_agent" in manifest.stored_artifacts
        and stages_full.get("assembler", {}).get("status") == "completed"
    )
    return {
        "run_id": manifest.run_id,
        "workbook_name": manifest.workbook_name,
        "workbook_file": manifest.workbook_file,
        "created_at": manifest.created_at,
        "updated_at": manifest.updated_at,
        "stages": {k: v.status.value for k, v in manifest.stages.items()},
        "stages_full": stages_full,
        "stored_artifacts": manifest.stored_artifacts,
        "adls_path": manifest.adls_path,
        "result_id": manifest.result_id,
        "completion_pct": round(completed / _TOTAL_STAGES * 100),
        "download_available": has_assembler,
    }


def _build_zip_tempfile(root: Path) -> Path:
    """Create a ZIP for *root* on disk and return its temporary path."""
    import zipfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        zip_path = Path(tmp.name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(root.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(root.parent)
                zf.write(file_path, arcname)

    return zip_path


def _zip_file_stream(zip_path: Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    """Stream ZIP bytes from disk in chunks and remove the temp file after."""
    try:
        with zip_path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    finally:
        try:
            os.unlink(zip_path)
        except FileNotFoundError:
            pass


@router.get("/{workbook_name}/{run_id}/download")
async def download_run(workbook_name: str, run_id: str) -> StreamingResponse:
    """Stream a ZIP of the assembled PBIP output for a run."""
    workbook_name = _validate_name(workbook_name, "workbook_name")
    run_id = _validate_name(run_id, "run_id")
    settings = get_agent_settings()
    assembler_dir = settings.runs_root / workbook_name / run_id / "pbip_project_assembler_agent"
    if not assembler_dir.is_dir():
        raise HTTPException(404, "No assembled output found for this run")

    zip_path = await asyncio.to_thread(_build_zip_tempfile, assembler_dir)
    filename = f"{workbook_name}_PBIP.zip"
    return StreamingResponse(
        _zip_file_stream(zip_path),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
