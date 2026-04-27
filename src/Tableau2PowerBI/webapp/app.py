"""FastAPI application wiring for Tableau2PowerBI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from Tableau2PowerBI.agents.assembler import PBIPProjectAssemblerAgent
from Tableau2PowerBI.agents.dax_measures import TmdlMeasuresGeneratorAgent
from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent
from Tableau2PowerBI.agents.metadata_extractor import TableauMetadataExtractorAgent
from Tableau2PowerBI.agents.report_visuals import PbirReportGeneratorAgent
from Tableau2PowerBI.agents.semantic_model import PBIPSemanticModelGeneratorAgent
from Tableau2PowerBI.agents.skeleton import PBIPProjectSkeletonAgent
from Tableau2PowerBI.agents.target_technical_doc import TargetTechnicalDocAgent
from Tableau2PowerBI.agents.warnings_reviewer import WarningsReviewerAgent, collect_warnings
from Tableau2PowerBI.core.config import get_agent_settings
from Tableau2PowerBI.core.run_history import RunHistory, compute_input_hash, resolve_stages_to_run
from Tableau2PowerBI.core.logging_setup import setup_logging
from Tableau2PowerBI.webapp.adls import upload_to_adls
from Tableau2PowerBI.webapp.documentation_routes import (
    build_documentation_stream_response,
    build_tdd_stream_response,
    build_warnings_review_stream_response,
    check_documentation_exists_response,
    get_documentation_html_response,
    get_documentation_md_response,
    get_tdd_html_response,
    get_tdd_md_response,
    warnings_collect_response,
)
from Tableau2PowerBI.webapp.pipeline_stream_routes import (
    build_analyze_stream_response,
    build_generate_stream_response,
)
from Tableau2PowerBI.webapp.runtime import (
    _result_store,
)
from Tableau2PowerBI.webapp.runtime import _SSELogHandler as _RuntimeSSELogHandler
from Tableau2PowerBI.webapp.runtime import (
    store_result,
)
from Tableau2PowerBI.webapp.settings import settings as webapp_settings

_WEBAPP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = _WEBAPP_DIR / "templates"
STATIC_DIR = _WEBAPP_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = {".twb", ".twbx"}
MAX_FILE_SIZE = webapp_settings.max_file_size_bytes
MAX_FILE_SIZE_MB = webapp_settings.max_file_size_mb
_SSELogHandler = _RuntimeSSELogHandler
_MAX_ACTIVE_PIPELINES = int(os.environ.get("WEBAPP_MAX_ACTIVE_PIPELINES", "2"))
_pipeline_slots = asyncio.Semaphore(max(_MAX_ACTIVE_PIPELINES, 1))

_FILE_PARAM = File(...)
_LANG_PARAM = Form(default="en")


def _upload_limit_message(max_file_size_mb: int) -> str:
    """Return the user-facing upload limit error message."""
    return f"File exceeds the {max_file_size_mb} MB limit"


def _validate_upload_content_length(request: Request, max_file_size: int, max_file_size_mb: int) -> None:
    """Reject requests that declare a body larger than the configured upload limit."""
    raw_length = request.headers.get("content-length")
    if not raw_length:
        return
    try:
        content_length = int(raw_length)
    except ValueError:
        raise HTTPException(400, "Invalid Content-Length header")
    if content_length > max_file_size:
        raise HTTPException(413, _upload_limit_message(max_file_size_mb))


def _get_history() -> RunHistory:
    """Build a RunHistory from current settings."""
    settings = get_agent_settings()
    return RunHistory(
        runs_root=settings.runs_root,
        output_root=settings.output_root,
        max_runs_per_workbook=settings.max_runs_per_workbook,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging when the app starts."""
    setup_logging()
    logger.info("Webapp started")
    yield


app = FastAPI(title="Tableau AI Analyzer", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """Prevent browser caching of JS/CSS during development."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


from Tableau2PowerBI.webapp.history import router as history_router  # noqa: E402

app.include_router(history_router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "upload_limit_mb": MAX_FILE_SIZE_MB,
            "upload_limit_bytes": MAX_FILE_SIZE,
        },
    )


@app.get("/results", response_class=HTMLResponse)
async def results_page(request: Request):
    return templates.TemplateResponse(request, "results.html")


@app.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request):
    return templates.TemplateResponse(request, "generate.html")


@app.get("/warnings", response_class=HTMLResponse)
async def warnings_page(request: Request):
    return templates.TemplateResponse(request, "warnings.html")


@app.get("/project/{workbook_name}", response_class=HTMLResponse)
async def project_page(request: Request, workbook_name: str):
    """Serve the project dashboard for a workbook."""
    from Tableau2PowerBI.webapp.history import _SAFE_NAME

    if not workbook_name or not _SAFE_NAME.fullmatch(workbook_name):
        raise HTTPException(400, f"Invalid workbook name: {workbook_name!r}")
    history = _get_history()
    if not history.list_runs(workbook_name):
        raise HTTPException(404, f"No runs found for workbook: {workbook_name}")
    return templates.TemplateResponse(request, "project.html")


@app.get("/api/results/{result_id}")
async def get_result(result_id: str):
    """Retrieve a previously stored analysis result by ID."""
    if not re.fullmatch(r"result_[a-zA-Z0-9]{1,32}", result_id):
        raise HTTPException(400, "Invalid result ID format")
    entry = _result_store.get(result_id)
    if not entry:
        raise HTTPException(404, "Result not found or expired")
    _, payload = entry
    return JSONResponse(content=json.loads(payload), media_type="application/json")


@app.post("/api/results/{result_id}")
async def save_result_endpoint(result_id: str, request: Request):
    """Store an analysis result from the client."""
    if not re.fullmatch(r"result_[a-zA-Z0-9]{1,32}", result_id):
        raise HTTPException(400, "Invalid result ID format")
    body = await request.body()
    if len(body) > 10 * 1024 * 1024:
        raise HTTPException(413, "Payload too large")
    store_result(result_id, body.decode("utf-8"))
    return JSONResponse({"status": "ok"})


@app.post("/analyze-stream")
async def analyze_stream(
    request: Request,
    file: UploadFile = _FILE_PARAM,
    lang: str = _LANG_PARAM,
):
    """Stream step-by-step progress of the analysis phase via SSE."""
    _ = lang
    _validate_upload_content_length(request, MAX_FILE_SIZE, MAX_FILE_SIZE_MB)
    async with _pipeline_slots:
        return await build_analyze_stream_response(
            file,
            upload_to_adls_fn=upload_to_adls,
            metadata_extractor_cls=TableauMetadataExtractorAgent,
            get_history_fn=_get_history,
            get_settings_fn=get_agent_settings,
            logger=logger,
            allowed_extensions=ALLOWED_EXTENSIONS,
            max_file_size=MAX_FILE_SIZE,
            max_file_size_mb=MAX_FILE_SIZE_MB,
        )


@app.post("/generate-stream")
async def generate_stream(request: Request):
    """Stream PBIP generation pipeline progress via SSE."""
    async with _pipeline_slots:
        return await build_generate_stream_response(
            request,
            metadata_extractor_cls=TableauMetadataExtractorAgent,
            target_technical_doc_cls=TargetTechnicalDocAgent,
            skeleton_agent_cls=PBIPProjectSkeletonAgent,
            semantic_model_agent_cls=PBIPSemanticModelGeneratorAgent,
            dax_measures_agent_cls=TmdlMeasuresGeneratorAgent,
            report_visuals_agent_cls=PbirReportGeneratorAgent,
            assembler_agent_cls=PBIPProjectAssemblerAgent,
            get_history_fn=_get_history,
            get_settings_fn=get_agent_settings,
            compute_input_hash_fn=compute_input_hash,
            resolve_stages_to_run_fn=resolve_stages_to_run,
            logger=logger,
        )


@app.post("/warnings-collect")
async def warnings_collect_endpoint(request: Request):
    """Collect warnings from all agent output directories for a workbook."""
    return await warnings_collect_response(
        request,
        collect_warnings_fn=collect_warnings,
        logger=logger,
    )


@app.post("/warnings-review-stream")
async def warnings_review_stream(request: Request):
    """Stream LLM-generated fix suggestions for migration warnings."""
    return await build_warnings_review_stream_response(
        request,
        warnings_reviewer_cls=WarningsReviewerAgent,
        logger=logger,
    )


@app.get("/documentation/{workbook_name}/html")
async def get_documentation_html(workbook_name: str):
    """Serve generated HTML functional documentation."""
    return get_documentation_html_response(workbook_name)


@app.get("/documentation/{workbook_name}/md")
async def get_documentation_md(workbook_name: str):
    """Serve generated Markdown functional documentation."""
    return get_documentation_md_response(workbook_name)


@app.get("/api/documentation/{workbook_name}/exists")
async def check_documentation_exists(workbook_name: str):
    """Return whether functional documentation artifacts exist."""
    return check_documentation_exists_response(workbook_name)


@app.get("/tdd/{workbook_name}/html")
async def get_tdd_html(workbook_name: str):
    """Serve generated HTML target technical documentation."""
    return get_tdd_html_response(workbook_name)


@app.get("/tdd/{workbook_name}/md")
async def get_tdd_md(workbook_name: str):
    """Serve generated Markdown target technical documentation."""
    return get_tdd_md_response(workbook_name)


@app.post("/documentation-stream")
async def documentation_stream(request: Request):
    """Stream functional documentation generation progress via SSE."""
    return await build_documentation_stream_response(
        request,
        functional_doc_cls=FunctionalDocAgent,
        get_history_fn=_get_history,
        logger=logger,
    )


@app.post("/tdd-stream")
async def tdd_stream(request: Request):
    """Stream target technical documentation generation progress via SSE."""
    return await build_tdd_stream_response(
        request,
        target_technical_doc_cls=TargetTechnicalDocAgent,
        get_history_fn=_get_history,
        logger=logger,
    )
