"""Project management routes: create named projects, upload reports, run pipelines."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from Tableau2PowerBI.agents.fdd_compare import FDDCompareAgent
from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent
from Tableau2PowerBI.agents.metadata_extractor import TableauMetadataExtractorAgent
from Tableau2PowerBI.agents.target_technical_doc import TargetTechnicalDocAgent
from Tableau2PowerBI.core.config import get_agent_settings
from Tableau2PowerBI.core.run_history import RunHistory, compute_input_hash, resolve_stages_to_run
from Tableau2PowerBI.webapp.adls import upload_to_adls
from Tableau2PowerBI.webapp.compare_routes import build_compare_stream_response
from Tableau2PowerBI.webapp.pipeline_stream_routes import (
    build_analyze_stream_response,
    build_generate_stream_response,
)
from Tableau2PowerBI.webapp.runtime import _sse_event
from Tableau2PowerBI.webapp.settings import settings as webapp_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

# Same pattern used in history.py for workbook/run name validation.
_SAFE_NAME = re.compile(r"^[\w\- .()]+$")

ALLOWED_EXTENSIONS = {".twb", ".twbx"}
MAX_FILE_SIZE = webapp_settings.max_file_size_bytes
MAX_FILE_SIZE_MB = webapp_settings.max_file_size_mb


# ── Storage helpers ──────────────────────────────────────────────────────────


def _projects_root() -> Path:
    """Return the root directory for all project data."""
    return Path("data/projects")


def _validate_name(value: str, label: str = "name") -> str:
    """Raise HTTP 400 if value contains path-traversal or forbidden characters."""
    if not value or not _SAFE_NAME.fullmatch(value):
        raise HTTPException(400, f"Invalid {label}: {value!r}")
    return value


def _project_dir(project_name: str) -> Path:
    return _projects_root() / project_name


def _load_project(project_name: str) -> dict:
    """Read project.json; raise HTTP 404 if the project does not exist."""
    path = _project_dir(project_name) / "project.json"
    if not path.exists():
        raise HTTPException(404, f"Project not found: {project_name!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_project(project_name: str, data: dict) -> None:
    """Write project.json atomically (write to .tmp then rename)."""
    path = _project_dir(project_name) / "project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _find_report(project: dict, workbook_name: str) -> dict | None:
    """Return the report entry matching workbook_name, or None."""
    return next((r for r in project.get("reports", []) if r["workbook_name"] == workbook_name), None)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_report_status(
    project_name: str,
    workbook_name: str,
    status: str,
    *,
    last_run_id: str | None = None,
    error: str | None = None,
) -> None:
    """Persist a report status change in project.json. Best-effort; never raises."""
    try:
        project = _load_project(project_name)
        report = _find_report(project, workbook_name)
        if report is None:
            return
        report["status"] = status
        if last_run_id is not None:
            report["last_run_id"] = last_run_id
        if error is not None:
            report["error"] = error
        elif status not in ("error",):
            report["error"] = None
        project["updated_at"] = _iso_now()
        _save_project(project_name, project)
    except Exception:
        logger.warning("Could not update report status: %s/%s → %s", project_name, workbook_name, status)


def _get_history() -> RunHistory:
    settings = get_agent_settings()
    return RunHistory(
        runs_root=settings.runs_root,
        output_root=settings.output_root,
        max_runs_per_workbook=settings.max_runs_per_workbook,
    )


# ── SSE helpers ──────────────────────────────────────────────────────────────


def _parse_sse_chunk(chunk: str | bytes) -> dict | None:
    """Extract the JSON payload from a single SSE 'data: ...' chunk."""
    if isinstance(chunk, bytes):
        chunk = chunk.decode("utf-8", errors="replace")
    for line in chunk.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                pass
    return None


class _FakeRequest:
    """Minimal shim satisfying the build_generate_stream_response contract (calls request.json())."""

    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self) -> dict:
        return self._body


# ── Pipeline chainer ─────────────────────────────────────────────────────────


async def _start_stream_gen(
    project_name: str,
    report: dict,
    file_path: Path,
) -> AsyncIterator[str]:
    """Chain analyze → generate for one report and relay all SSE events to the client.

    Reuses build_analyze_stream_response and build_generate_stream_response unchanged;
    iterates their StreamingResponse.body_iterator to relay chunks and extract the
    run_id / metadata_json needed to bridge the two phases.
    """
    workbook_name = report["workbook_name"]
    _update_report_status(project_name, workbook_name, "running")

    try:
        # ── Phase 1: Analyze (metadata extraction) ──────────────────────────
        file_bytes = await asyncio.to_thread(file_path.read_bytes)

        # SpooledTemporaryFile lets UploadFile.read() work the same as a real upload.
        spooled = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)
        spooled.write(file_bytes)
        spooled.seek(0)
        fake_upload = UploadFile(filename=report["filename"], file=spooled)

        analyze_resp = await build_analyze_stream_response(
            fake_upload,
            upload_to_adls_fn=upload_to_adls,
            metadata_extractor_cls=TableauMetadataExtractorAgent,
            get_history_fn=_get_history,
            get_settings_fn=get_agent_settings,
            logger=logger,
            allowed_extensions=ALLOWED_EXTENSIONS,
            max_file_size=MAX_FILE_SIZE,
            max_file_size_mb=MAX_FILE_SIZE_MB,
        )

        run_id = None
        metadata_json = None
        async for chunk in analyze_resp.body_iterator:
            yield chunk
            event = _parse_sse_chunk(chunk)
            if not event:
                continue
            if event.get("step") == "complete":
                run_id = event.get("run_id")
                metadata_json = event.get("result")
            elif event.get("step") == "error":
                _update_report_status(
                    project_name, workbook_name, "error",
                    error=event.get("message", "Analyze failed"),
                )
                return

        if not run_id or not metadata_json:
            msg = "Analyze phase did not return a run_id"
            _update_report_status(project_name, workbook_name, "error", error=msg)
            yield _sse_event({"step": "error", "message": msg})
            return

        # ── Phase 2: Generate (full PBIP pipeline) ───────────────────────────
        fake_request = _FakeRequest(
            {
                "metadata_json": metadata_json,
                # twb_path is used only to derive workbook_name via Path(twb_path).stem
                "twb_path": str(file_path),
                "semantic_model_name": workbook_name,
                "run_id": run_id,
                "force_stages": None,
            }
        )

        gen_resp = await build_generate_stream_response(
            fake_request,
            metadata_extractor_cls=TableauMetadataExtractorAgent,
            functional_doc_agent_cls=FunctionalDocAgent,
            target_technical_doc_cls=TargetTechnicalDocAgent,
            get_history_fn=_get_history,
            get_settings_fn=get_agent_settings,
            compute_input_hash_fn=compute_input_hash,
            resolve_stages_to_run_fn=resolve_stages_to_run,
            logger=logger,
        )

        async for chunk in gen_resp.body_iterator:
            yield chunk
            event = _parse_sse_chunk(chunk)
            if event and event.get("step") == "error":
                _update_report_status(
                    project_name, workbook_name, "error",
                    error=event.get("message", "Generate failed"),
                )
                return

        _update_report_status(project_name, workbook_name, "complete", last_run_id=run_id)

    except Exception as exc:
        logger.error("start-stream error for %s/%s: %s", project_name, workbook_name, exc)
        _update_report_status(project_name, workbook_name, "error", error=str(exc))
        yield _sse_event({"step": "error", "message": str(exc)})


# ── API Routes ───────────────────────────────────────────────────────────────


@router.post("", status_code=201)
async def create_project(request: Request) -> JSONResponse:
    """Create a new named project.  Body: ``{"name": "My Project"}``."""
    body = await request.json()
    name = _validate_name(body.get("name", "").strip())
    if (_project_dir(name) / "project.json").exists():
        raise HTTPException(409, f"Project already exists: {name!r}")
    project: dict = {
        "name": name,
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
        "reports": [],
    }
    _save_project(name, project)
    logger.info("Project created: %s", name)
    return JSONResponse(project, status_code=201)


@router.get("")
async def list_projects() -> JSONResponse:
    """Return all projects sorted by name."""
    root = _projects_root()
    if not root.exists():
        return JSONResponse([])
    projects = []
    for entry in sorted(root.iterdir()):
        p = entry / "project.json"
        if p.exists():
            try:
                projects.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
    return JSONResponse(projects)


@router.get("/{project_name}")
async def get_project(project_name: str) -> JSONResponse:
    """Return the full project object including its reports list."""
    _validate_name(project_name)
    return JSONResponse(_load_project(project_name))


@router.post("/{project_name}/reports")
async def upload_report(project_name: str, file: UploadFile = File(...)) -> JSONResponse:
    """Upload a .twb or .twbx file and register it in the project."""
    _validate_name(project_name)
    project = _load_project(project_name)

    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format '{ext}'. Use .twb or .twbx")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File exceeds the {MAX_FILE_SIZE_MB} MB limit")

    workbook_name = Path(filename).stem
    if _find_report(project, workbook_name):
        raise HTTPException(409, f"Report '{workbook_name}' already exists in this project")

    files_dir = _project_dir(project_name) / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    (files_dir / filename).write_bytes(file_bytes)

    project["reports"].append(
        {
            "filename": filename,
            "workbook_name": workbook_name,
            "uploaded_at": _iso_now(),
            "status": "pending",
            "last_run_id": None,
            "error": None,
        }
    )
    project["updated_at"] = _iso_now()
    _save_project(project_name, project)
    logger.info("Report uploaded: %s → project %s", filename, project_name)
    return JSONResponse(project)


@router.post("/{project_name}/reports/{workbook_name}/start-stream")
async def start_report_stream(project_name: str, workbook_name: str) -> StreamingResponse:
    """Run the full analyze + generate pipeline for one report. Streams SSE events."""
    _validate_name(project_name)
    _validate_name(workbook_name)

    project = _load_project(project_name)
    report = _find_report(project, workbook_name)
    if not report:
        raise HTTPException(404, f"Report '{workbook_name}' not found in project '{project_name}'")

    if report.get("status") == "running":
        raise HTTPException(409, "Pipeline is already running for this report")

    file_path = _project_dir(project_name) / "files" / report["filename"]
    if not file_path.exists():
        raise HTTPException(404, f"Uploaded file not found: {report['filename']}")

    return StreamingResponse(
        _start_stream_gen(project_name, report, file_path),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.delete("/{project_name}", status_code=204)
async def delete_project(project_name: str) -> None:
    """Permanently delete a project directory and all its files."""
    _validate_name(project_name)
    project_dir = _project_dir(project_name)
    if not (project_dir / "project.json").exists():
        raise HTTPException(404, f"Project not found: {project_name!r}")
    await asyncio.to_thread(shutil.rmtree, str(project_dir), True)
    logger.info("Project deleted: %s", project_name)


@router.delete("/{project_name}/reports/{workbook_name}")
async def delete_report(project_name: str, workbook_name: str) -> JSONResponse:
    """Remove a report entry and its uploaded file from a project."""
    _validate_name(project_name)
    _validate_name(workbook_name)
    project = _load_project(project_name)
    report = _find_report(project, workbook_name)
    if not report:
        raise HTTPException(404, f"Report '{workbook_name}' not found in project '{project_name}'")
    if report.get("status") == "running":
        raise HTTPException(409, "Cannot delete a report while its pipeline is running")
    file_path = _project_dir(project_name) / "files" / report["filename"]
    if file_path.exists():
        file_path.unlink()
    project["reports"] = [r for r in project["reports"] if r["workbook_name"] != workbook_name]
    project["updated_at"] = _iso_now()
    _save_project(project_name, project)
    logger.info("Report deleted: %s from project %s", workbook_name, project_name)
    return JSONResponse(project)


# ── Comparison helpers ───────────────────────────────────────────────────────


def _compare_dir(project_name: str, compare_id: str) -> Path:
    return _project_dir(project_name) / "comparisons" / compare_id


def _validate_compare_id(compare_id: str) -> str:
    if not compare_id or not re.fullmatch(r"cmp_[\w]+", compare_id):
        raise HTTPException(400, f"Invalid compare_id: {compare_id!r}")
    return compare_id


def _load_compare_meta(compare_dir: Path) -> dict:
    path = compare_dir / "meta.json"
    if not path.exists():
        raise HTTPException(404, "Comparison not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_compare_meta(compare_dir: Path, meta: dict) -> None:
    compare_dir.mkdir(parents=True, exist_ok=True)
    tmp = compare_dir / "meta.tmp"
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(compare_dir / "meta.json")


def _update_compare_status(
    project_name: str,
    compare_id: str,
    status: str,
    *,
    verdict_summary: dict | None = None,
    error: str | None = None,
) -> None:
    """Persist a comparison status change in meta.json. Best-effort; never raises."""
    try:
        cdir = _compare_dir(project_name, compare_id)
        meta = _load_compare_meta(cdir)
        meta["status"] = status
        if verdict_summary is not None:
            meta["verdict_summary"] = verdict_summary
        if error is not None:
            meta["error"] = error
        elif status != "error":
            meta["error"] = None
        _save_compare_meta(cdir, meta)
    except Exception:
        logger.warning("Could not update compare status: %s/%s → %s", project_name, compare_id, status)


# ── Comparison SSE generator ─────────────────────────────────────────────────


async def _compare_stream_gen(project_name: str, compare_id: str) -> AsyncIterator[str]:
    """Run FDDCompareAgent on the FDD files listed in meta.json and stream SSE events."""
    cdir = _compare_dir(project_name, compare_id)
    meta = _load_compare_meta(cdir)
    workbook_names: list[str] = meta["workbook_names"]
    _update_compare_status(project_name, compare_id, "running")

    try:
        settings = get_agent_settings()
        fdd_docs: dict[str, str] = {}
        for wb in workbook_names:
            fdd_path = (
                settings.output_root
                / "tableau_functional_doc_agent"
                / wb
                / "functional_documentation.md"
            )
            if not fdd_path.exists():
                raise FileNotFoundError(
                    f"FDD not found for '{wb}'. Generate FDD first via the FDD button."
                )
            fdd_docs[wb] = await asyncio.to_thread(fdd_path.read_text, encoding="utf-8")

        resp = await build_compare_stream_response(
            fdd_docs,
            compare_agent_cls=FDDCompareAgent,
            logger=logger,
        )

        result_data = None
        async for chunk in resp.body_iterator:
            yield chunk
            event = _parse_sse_chunk(chunk)
            if not event:
                continue
            if event.get("state") == "complete":
                result_data = event.get("result")
            elif event.get("state") == "error":
                _update_compare_status(
                    project_name, compare_id, "error", error=event.get("message")
                )
                return

        if result_data:
            (cdir / "result.json").write_text(
                json.dumps(result_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            if narrative := result_data.get("narrative"):
                (cdir / "report.md").write_text(narrative, encoding="utf-8")
            groups = result_data.get("groups", [])
            verdict_summary = {
                "merge_count": sum(1 for g in groups if g.get("verdict") == "merge"),
                "separate_count": sum(1 for g in groups if g.get("verdict") == "keep_separate"),
                "borderline_count": sum(1 for g in groups if g.get("verdict") == "borderline"),
            }
            _update_compare_status(
                project_name, compare_id, "complete", verdict_summary=verdict_summary
            )

    except Exception as exc:
        logger.error("compare-stream error %s/%s: %s", project_name, compare_id, exc)
        _update_compare_status(project_name, compare_id, "error", error=str(exc))
        yield _sse_event({"state": "error", "message": str(exc)})


# ── Comparison API Routes ────────────────────────────────────────────────────


@router.post("/{project_name}/comparisons", status_code=201)
async def create_comparison(project_name: str, request: Request) -> JSONResponse:
    """Create a new comparison run. Body: ``{"workbook_names": ["A", "B", ...]}``."""
    _validate_name(project_name)
    _load_project(project_name)  # raises 404 if project doesn't exist
    body = await request.json()
    workbook_names: list[str] = body.get("workbook_names", [])
    if len(workbook_names) < 2:
        raise HTTPException(400, "At least 2 workbook_names are required")
    for wb in workbook_names:
        _validate_name(wb, label="workbook_name")

    from datetime import datetime, timezone  # already imported but re-stated for clarity
    compare_id = "cmp_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
    meta: dict = {
        "id": compare_id,
        "created_at": _iso_now(),
        "status": "pending",
        "workbook_names": workbook_names,
        "verdict_summary": None,
        "error": None,
    }
    cdir = _compare_dir(project_name, compare_id)
    _save_compare_meta(cdir, meta)
    logger.info("Comparison created: %s in project %s", compare_id, project_name)
    return JSONResponse(meta, status_code=201)


@router.get("/{project_name}/comparisons")
async def list_comparisons(project_name: str) -> JSONResponse:
    """Return all comparisons for a project, newest first."""
    _validate_name(project_name)
    _load_project(project_name)
    cmp_root = _project_dir(project_name) / "comparisons"
    if not cmp_root.exists():
        return JSONResponse([])
    comparisons = []
    for entry in sorted(cmp_root.iterdir(), reverse=True):
        meta_path = entry / "meta.json"
        if meta_path.exists():
            try:
                comparisons.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except Exception:
                pass
    return JSONResponse(comparisons)


@router.get("/{project_name}/comparisons/{compare_id}")
async def get_comparison(project_name: str, compare_id: str) -> JSONResponse:
    """Return meta.json merged with result.json for a specific comparison."""
    _validate_name(project_name)
    _validate_compare_id(compare_id)
    cdir = _compare_dir(project_name, compare_id)
    meta = _load_compare_meta(cdir)
    result_path = cdir / "result.json"
    if result_path.exists():
        try:
            meta["result"] = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return JSONResponse(meta)


@router.get("/{project_name}/comparisons/{compare_id}/report-md")
async def get_comparison_report_md(project_name: str, compare_id: str):
    """Download the narrative markdown report for a completed comparison."""
    from fastapi.responses import FileResponse

    _validate_name(project_name)
    _validate_compare_id(compare_id)
    report_path = _compare_dir(project_name, compare_id) / "report.md"
    if not report_path.exists():
        raise HTTPException(404, "Report not yet generated")
    return FileResponse(
        str(report_path),
        media_type="text/markdown",
        filename=f"comparison_{compare_id}.md",
    )


@router.post("/{project_name}/comparisons/{compare_id}/stream")
async def start_comparison_stream(project_name: str, compare_id: str) -> StreamingResponse:
    """Run the FDD comparison pipeline. Streams SSE events."""
    _validate_name(project_name)
    _validate_compare_id(compare_id)
    cdir = _compare_dir(project_name, compare_id)
    meta = _load_compare_meta(cdir)
    if meta.get("status") == "running":
        raise HTTPException(409, "Comparison is already running")
    return StreamingResponse(
        _compare_stream_gen(project_name, compare_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
