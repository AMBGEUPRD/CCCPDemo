"""Documentation, warnings, and TDD route implementations."""

import json
import logging
import traceback
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from Tableau2PowerBI.core.run_history import StageStatus
from Tableau2PowerBI.core.utils import get_output_dir
from Tableau2PowerBI.webapp.runtime import (
    _capture_logs_for_sse,
    _drain_log_queue,
    _result_store,
    _run_with_logs,
    _sse_event,
    store_result,
)


def _parse_sse_data_payload(event: str) -> dict[str, Any] | None:
    """Extract the JSON payload from an SSE event string."""
    if not event:
        return None

    for line in event.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            payload = json.loads(line[6:])
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            return payload
        return None

    return None


def _extract_tdd_phase(event: str) -> str | None:
    """Return the TDD phase label embedded in a streamed log event."""
    payload = _parse_sse_data_payload(event)
    if payload is None or payload.get("type") != "log":
        return None

    message = payload.get("message")
    if not isinstance(message, str) or "[TDD:PHASE]" not in message:
        return None

    return message.split("[TDD:PHASE]", 1)[1].strip()


def get_documentation_html_response(workbook_name: str) -> FileResponse:
    """Serve generated HTML functional documentation."""
    doc_dir = get_output_dir("tableau_functional_doc_agent", workbook_name)
    html_path = doc_dir / "functional_documentation.html"
    if not html_path.exists():
        raise HTTPException(
            404,
            f"HTML documentation not found for '{workbook_name}'. Generate it first via /documentation-stream.",
        )
    return FileResponse(str(html_path), media_type="text/html")


def get_documentation_md_response(workbook_name: str) -> FileResponse:
    """Serve generated Markdown functional documentation."""
    doc_dir = get_output_dir("tableau_functional_doc_agent", workbook_name)
    md_path = doc_dir / "functional_documentation.md"
    if not md_path.exists():
        raise HTTPException(
            404,
            f"Markdown documentation not found for '{workbook_name}'. Generate it first via /documentation-stream.",
        )
    return FileResponse(
        str(md_path),
        media_type="text/markdown",
        filename=f"{workbook_name}_functional_documentation.md",
    )


def check_documentation_exists_response(workbook_name: str) -> dict[str, bool]:
    """Report whether functional documentation artifacts exist."""
    doc_dir = get_output_dir("tableau_functional_doc_agent", workbook_name)
    html_exists = (doc_dir / "functional_documentation.html").exists()
    md_exists = (doc_dir / "functional_documentation.md").exists()
    return {"exists": html_exists or md_exists}


def get_tdd_html_response(workbook_name: str) -> FileResponse:
    """Serve generated HTML TDD."""
    tdd_dir = get_output_dir("target_technical_doc_agent", workbook_name)
    html_path = tdd_dir / "target_technical_documentation.html"
    if not html_path.exists():
        raise HTTPException(
            404,
            f"TDD HTML not found for '{workbook_name}'. Generate it first via /tdd-stream or the pipeline.",
        )
    return FileResponse(str(html_path), media_type="text/html")


def get_tdd_md_response(workbook_name: str) -> FileResponse:
    """Serve generated Markdown TDD."""
    tdd_dir = get_output_dir("target_technical_doc_agent", workbook_name)
    md_path = tdd_dir / "target_technical_documentation.md"
    if not md_path.exists():
        raise HTTPException(
            404,
            f"TDD Markdown not found for '{workbook_name}'. Generate it first via /tdd-stream or the pipeline.",
        )
    return FileResponse(
        str(md_path),
        media_type="text/markdown",
        filename=f"{workbook_name}_target_technical_documentation.md",
    )


async def warnings_collect_response(
    request: Request,
    *,
    collect_warnings_fn,
    logger: logging.Logger,
) -> dict:
    """Handle POST /warnings-collect."""
    body = await request.json()
    workbook_name = (body.get("workbook_name") or "").strip()
    if not workbook_name:
        raise HTTPException(400, "workbook_name is required")

    try:
        return collect_warnings_fn(workbook_name)
    except Exception as exc:
        logger.error("Warning collection failed: %s", exc)
        raise HTTPException(500, str(exc)) from exc


async def build_warnings_review_stream_response(
    request: Request,
    *,
    warnings_reviewer_cls,
    logger: logging.Logger,
) -> StreamingResponse:
    """Build the response for POST /warnings-review-stream."""
    body = await request.json()
    warnings_payload: dict = body.get("warnings", {})

    if not isinstance(warnings_payload, dict):
        raise HTTPException(400, "warnings must be a JSON object")

    async def _stream():
        with _capture_logs_for_sse() as log_queue:
            try:
                yield _sse_event({"state": "running", "label": "Reviewing migration warnings..."})
                logger.info("[WarningsReview] Submitting %d warning(s)", warnings_payload.get("total_warnings", 0))

                def _run_review() -> dict:
                    agent = warnings_reviewer_cls()
                    try:
                        agent.create()
                        return agent.review_warnings(warnings_payload)
                    finally:
                        agent.close()

                holder: list = []
                async for event in _run_with_logs(_run_review, log_queue, holder):
                    yield event

                review_result = holder[0]
                for event in _drain_log_queue(log_queue):
                    yield event

                yield _sse_event({"state": "complete", "status": "ok", "review": review_result})
            except Exception as exc:
                logger.error("Warnings review failed: %s\n%s", exc, traceback.format_exc())
                for event in _drain_log_queue(log_queue):
                    yield event
                yield _sse_event({"state": "error", "message": str(exc)})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def build_documentation_stream_response(
    request: Request,
    *,
    functional_doc_cls,
    get_history_fn: Callable[[], Any],
    logger: logging.Logger,
) -> StreamingResponse:
    """Build the response for POST /documentation-stream."""
    body = await request.json()
    workbook_name = (body.get("workbook_name") or "").strip()
    data_folder = body.get("data_folder") or None
    run_id = body.get("run_id") or None

    if not workbook_name:
        raise HTTPException(400, "workbook_name is required")

    result_id = body.get("result_id") or None

    async def _stream():
        with _capture_logs_for_sse() as log_queue:
            try:
                yield _sse_event({"state": "running", "label": "Generating functional documentation..."})
                logger.info("[FunctionalDoc] Generating docs for '%s'", workbook_name)

                def _run_doc() -> dict:
                    agent = functional_doc_cls()
                    try:
                        agent.create()
                        md_path, html_path = agent.generate_documentation(
                            workbook_name,
                            data_folder_path=data_folder,
                        )
                        return {
                            "markdown_path": str(md_path),
                            "html_path": str(html_path),
                        }
                    finally:
                        agent.close()

                holder: list = []
                async for event in _run_with_logs(_run_doc, log_queue, holder):
                    yield event

                doc_result = holder[0]
                for event in _drain_log_queue(log_queue):
                    yield event

                if result_id and result_id in _result_store:
                    _, existing_json = _result_store[result_id]
                    try:
                        existing = json.loads(existing_json)
                        existing["documentation"] = doc_result
                        store_result(result_id, json.dumps(existing, ensure_ascii=False))
                    except Exception:
                        logger.debug(
                            "Failed to update result store for %s",
                            result_id,
                            exc_info=True,
                        )

                if run_id:
                    try:
                        history = get_history_fn()
                        manifest = history.load_run(workbook_name, run_id)
                        history.update_stage(
                            manifest,
                            "functional_doc",
                            status=StageStatus.COMPLETED,
                            deterministic=False,
                        )
                        history.store_artifacts(manifest, "tableau_functional_doc_agent")
                    except Exception as exc:
                        logger.warning("Run history update failed: %s", exc)

                yield _sse_event({"state": "complete", "status": "ok", "documentation": doc_result})
            except Exception as exc:
                logger.error("Functional doc failed: %s\n%s", exc, traceback.format_exc())
                for event in _drain_log_queue(log_queue):
                    yield event
                yield _sse_event({"state": "error", "message": str(exc)})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def build_tdd_stream_response(
    request: Request,
    *,
    target_technical_doc_cls,
    get_history_fn: Callable[[], Any],
    logger: logging.Logger,
) -> StreamingResponse:
    """Build the response for POST /tdd-stream."""
    body = await request.json()
    workbook_name = (body.get("workbook_name") or "").strip()
    run_id = body.get("run_id") or None

    if not workbook_name:
        raise HTTPException(400, "workbook_name is required")

    async def _stream():
        with _capture_logs_for_sse(min_level=logging.INFO) as log_queue:
            current_phase = None

            def _phase_step(phase_label: str | None) -> int | None:
                if not phase_label:
                    return None
                if phase_label.startswith("1/2"):
                    return 1
                if phase_label.startswith("2/2"):
                    return 2
                return None

            try:
                yield _sse_event(
                    {
                        "state": "running",
                        "label": "Generating target technical documentation...",
                        "phase": None,
                        "phase_step": None,
                    }
                )
                logger.info("[TDD] Generating TDD for '%s'", workbook_name)

                def _run_tdd() -> dict:
                    agent = target_technical_doc_cls()
                    try:
                        agent.create()
                        tdd = agent.generate_tdd(workbook_name)
                        assessment = None
                        try:
                            tdd_dir = get_output_dir("target_technical_doc_agent", workbook_name)
                            assess_path = tdd_dir / "migration_assessment.json"
                            if assess_path.exists():
                                assessment = json.loads(assess_path.read_text(encoding="utf-8"))
                        except Exception:
                            logger.debug(
                                "Could not read migration_assessment.json for %s",
                                workbook_name,
                                exc_info=True,
                            )
                        return {
                            "tables": len(tdd.semantic_model.tables),
                            "measures": len(tdd.dax_measures.measures),
                            "pages": len(tdd.report.pages),
                            "migration_assessment": assessment,
                        }
                    finally:
                        agent.close()

                holder: list = []
                async for event in _run_with_logs(_run_tdd, log_queue, holder):
                    phase_label = _extract_tdd_phase(event)
                    if phase_label is not None:
                        current_phase = phase_label
                        yield _sse_event(
                            {
                                "state": "running",
                                "label": "Generating target technical documentation...",
                                "phase": current_phase,
                                "phase_step": _phase_step(current_phase),
                            }
                        )
                    yield event

                tdd_result = holder[0]
                for event in _drain_log_queue(log_queue):
                    phase_label = _extract_tdd_phase(event)
                    if phase_label is not None:
                        current_phase = phase_label
                        yield _sse_event(
                            {
                                "state": "running",
                                "label": "Generating target technical documentation...",
                                "phase": current_phase,
                                "phase_step": _phase_step(current_phase),
                            }
                        )
                    yield event

                if run_id:
                    try:
                        history = get_history_fn()
                        manifest = history.load_run(workbook_name, run_id)
                        history.update_stage(
                            manifest,
                            "target_technical_doc",
                            status=StageStatus.COMPLETED,
                            deterministic=False,
                        )
                        history.store_artifacts(manifest, "target_technical_doc_agent")
                    except Exception as exc:
                        logger.warning("Run history update failed: %s", exc)

                yield _sse_event({"state": "complete", "status": "ok", "tdd": tdd_result})
            except Exception as exc:
                logger.error("TDD generation failed: %s\n%s", exc, traceback.format_exc())
                for event in _drain_log_queue(log_queue):
                    phase_label = _extract_tdd_phase(event)
                    if phase_label is not None:
                        current_phase = phase_label
                        yield _sse_event(
                            {
                                "state": "running",
                                "label": "Generating target technical documentation...",
                                "phase": current_phase,
                                "phase_step": _phase_step(current_phase),
                            }
                        )
                    yield event
                yield _sse_event({"state": "error", "message": str(exc)})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
