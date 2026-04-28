"""Streaming pipeline route implementations for the webapp."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import traceback
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from Tableau2PowerBI.core.run_history import STAGE_GRAPH, StageStatus
from Tableau2PowerBI.core.output_dirs import get_output_dir
from Tableau2PowerBI.webapp.runtime import (
    _capture_logs_for_sse,
    _drain_log_queue,
    _format_pipeline_result_for_display,
    _iso_now,
    _run_pipeline_stage,
    _run_with_logs,
    _sse_event,
    store_result,
)


async def build_analyze_stream_response(
    file: UploadFile,
    *,
    upload_to_adls_fn,
    metadata_extractor_cls,
    get_history_fn: Callable[[], Any],
    get_settings_fn: Callable[[], Any],
    logger: logging.Logger,
    allowed_extensions: set[str],
    max_file_size: int,
    max_file_size_mb: int,
) -> StreamingResponse:
    """Build the response for POST /analyze-stream."""
    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(400, f"Unsupported format '{ext}'. Use .twb or .twbx")

    file_bytes = await file.read()
    if len(file_bytes) > max_file_size:
        raise HTTPException(413, f"File exceeds the {max_file_size_mb} MB limit")

    logger.info("Received: %s (%s bytes)", filename, f"{len(file_bytes):,}")

    safe_filename = Path(filename).name or f"upload{ext}"
    temp_dir = tempfile.TemporaryDirectory()
    local_path = Path(temp_dir.name) / safe_filename
    local_path.write_bytes(file_bytes)

    async def _stream():
        adls_path = None
        result = None
        with _capture_logs_for_sse() as log_queue:
            try:
                yield _sse_event({"step": 1, "state": "running", "label": "Uploading to secure storage"})
                logger.info("[Step 1/2] Uploading to secure storage")
                try:
                    adls_path = await asyncio.to_thread(upload_to_adls_fn, file_bytes, filename)
                    logger.info("Uploaded to ADLS")
                except Exception as exc:
                    logger.warning("ADLS upload skipped: %s", exc)
                for event in _drain_log_queue(log_queue):
                    yield event
                yield _sse_event({"step": 1, "state": "done"})

                yield _sse_event({"step": 2, "state": "running", "label": "Parsing Tableau workbook"})
                logger.info("[Step 2/2] Parsing Tableau workbook")
                agent = metadata_extractor_cls()
                holder: list = []
                async for event in _run_with_logs(
                    lambda: agent.extract_tableau_metadata(str(local_path)),
                    log_queue,
                    holder,
                ):
                    yield event
                result = holder[0]
                logger.info("Parsing complete")
                for event in _drain_log_queue(log_queue):
                    yield event
                yield _sse_event({"step": 2, "state": "done"})

                result_id = f"result_{uuid.uuid4().hex[:12]}"
                coerced = _format_pipeline_result_for_display(result)

                history = get_history_fn()
                workbook_name = Path(filename).stem
                manifest = history.create_run(workbook_name, filename)
                manifest.adls_path = adls_path
                history.update_stage(
                    manifest,
                    "metadata_extractor",
                    status=StageStatus.COMPLETED,
                    deterministic=True,
                )

                settings = get_settings_fn()
                analysis_out = (
                    settings.output_root / "tableau_metadata_extractor_agent" / workbook_name / "analysis_result.json"
                )
                analysis_out.parent.mkdir(parents=True, exist_ok=True)
                analysis_out.write_text(coerced, encoding="utf-8")

                history.store_artifacts(manifest, "tableau_metadata_extractor_agent")
                manifest.result_id = result_id
                history.save_run(manifest)

                final_payload = {
                    "step": "complete",
                    "status": "ok",
                    "result_id": result_id,
                    "run_id": manifest.run_id,
                    "filename": filename,
                    "adls_path": adls_path,
                    "result": coerced,
                }
                yield _sse_event(final_payload)

                store_result(
                    result_id,
                    json.dumps(
                        {
                            "id": result_id,
                            "run_id": manifest.run_id,
                            "filename": filename,
                            "adls_path": adls_path,
                            "result": coerced,
                            "timestamp": _iso_now(),
                        },
                        ensure_ascii=False,
                    ),
                )

            except Exception as exc:
                logger.error("Extraction error: %s\n%s", exc, traceback.format_exc())
                yield _sse_event({"step": "error", "message": str(exc)})
            finally:
                temp_dir.cleanup()

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def build_generate_stream_response(
    request: Request,
    *,
    metadata_extractor_cls,
    functional_doc_agent_cls,
    target_technical_doc_cls,
    get_history_fn: Callable[[], Any],
    get_settings_fn: Callable[[], Any],
    compute_input_hash_fn,
    resolve_stages_to_run_fn,
    logger: logging.Logger,
) -> StreamingResponse:
    """Build the response for POST /generate-stream."""
    body = await request.json()
    metadata_json = body.get("metadata_json", "")
    twb_path = body.get("twb_path", "")
    run_id = body.get("run_id") or None
    force_stages_list: list[str] | None = body.get("force_stages")

    if force_stages_list:
        valid_stages = set(STAGE_GRAPH.keys())
        invalid = set(force_stages_list) - valid_stages
        if invalid:
            raise HTTPException(
                422,
                f"Unknown stage names: {', '.join(sorted(invalid))}. " f"Valid: {', '.join(sorted(valid_stages))}",
            )

    try:
        json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
    except Exception as exc:
        raise HTTPException(400, "Invalid metadata JSON") from exc

    if not twb_path:
        raise HTTPException(400, "twb_path is required to derive the workbook name")

    workbook_name = Path(twb_path).stem

    stages_to_run: set[str] | None = None
    manifest = None
    if run_id:
        try:
            history = get_history_fn()
            manifest = history.load_run(workbook_name, run_id)
            history.restore_run(manifest)
            force_set = set(force_stages_list) if force_stages_list else None
            webapp_generate_stages = {
                "metadata_extractor",
                "functional_doc",
                "target_technical_doc",
            }
            stages_to_run = resolve_stages_to_run_fn(
                manifest,
                current_hashes={
                    "metadata_extractor": compute_input_hash_fn(
                        [Path("data/input") / (manifest.workbook_file or Path(twb_path).name)]
                    ),
                    "functional_doc": compute_input_hash_fn(
                        [
                            get_output_dir("tableau_metadata_extractor_agent", workbook_name)
                            / "functional_doc_input_slim.json"
                        ]
                    ),
                    "target_technical_doc": compute_input_hash_fn(
                        [
                            get_output_dir("tableau_metadata_extractor_agent", workbook_name)
                            / "semantic_model_input.json",
                            get_output_dir("tableau_metadata_extractor_agent", workbook_name) / "report_input.json",
                            get_output_dir("tableau_functional_doc_agent", workbook_name)
                            / "functional_documentation.json",
                        ]
                    ),
                },
                force_stages=force_set,
                pipeline_stages=webapp_generate_stages,
            )
            logger.info("[Generate] Selective: %s", ", ".join(sorted(stages_to_run)) or "(all cached)")
        except Exception as exc:
            logger.warning("Could not load run %s: %s", run_id, exc)

    def _run_metadata_extractor() -> str:
        input_file = Path("data/input") / (manifest.workbook_file if manifest else Path(twb_path).name)
        if not input_file.exists():
            input_file = Path(twb_path) if twb_path else input_file
        if not input_file.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        agent = metadata_extractor_cls()
        result = agent.extract_tableau_metadata(str(input_file))
        settings = get_settings_fn()
        out = settings.output_root / "tableau_metadata_extractor_agent" / workbook_name / "analysis_result.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result, encoding="utf-8")
        return "Metadata re-extracted"

    def _run_functional_doc() -> str:
        fdd_out = get_output_dir("tableau_functional_doc_agent", workbook_name) / "functional_documentation.json"
        if fdd_out.exists():
            logger.info("FDD already exists — skipping regeneration")
            return "Functional documentation already exists (reused)"
        agent = functional_doc_agent_cls()
        try:
            agent.create()
            agent.generate_documentation(workbook_name)
            return "Functional documentation generated."
        finally:
            agent.close()

    def _run_tdd() -> str:
        tdd_dir = get_output_dir("target_technical_doc_agent", workbook_name)
        sm_path = tdd_dir / "semantic_model_design.json"
        dax_path = tdd_dir / "dax_measures_design.json"
        rpt_path = tdd_dir / "report_design.json"
        if sm_path.exists() and dax_path.exists() and rpt_path.exists():
            logger.info("TDD already exists — skipping regeneration")
            return "TDD already generated (reused from analysis step)"

        agent = target_technical_doc_cls()
        agent.create()
        tdd = agent.generate_tdd(workbook_name)
        return (
            f"TDD generated: {len(tdd.semantic_model.tables)} tables, "
            f"{len(tdd.dax_measures.measures)} measures, "
            f"{len(tdd.report.pages)} pages"
        )

    pipeline = [
        ("tableau_metadata_extractor", "Metadata Extraction", _run_metadata_extractor),
        ("tableau_functional_doc", "Functional Documentation", _run_functional_doc),
        ("target_technical_doc", "Technical Design Document", _run_tdd),
    ]

    agent_to_stage = {
        "tableau_metadata_extractor": "metadata_extractor",
        "tableau_functional_doc": "functional_doc",
        "target_technical_doc": "target_technical_doc",
    }
    stage_to_agent_dir = {
        "metadata_extractor": "tableau_metadata_extractor_agent",
        "functional_doc": "tableau_functional_doc_agent",
        "target_technical_doc": "target_technical_doc_agent",
    }

    skipped_agents: list[tuple[str, str]] = []
    if stages_to_run is not None:
        original_pipeline = pipeline
        pipeline = [
            (agent_id, agent_label, run_fn)
            for agent_id, agent_label, run_fn in original_pipeline
            if agent_to_stage.get(agent_id, agent_id) in stages_to_run
        ]
        skipped_agents = [
            (agent_id, agent_label)
            for agent_id, agent_label, _ in original_pipeline
            if agent_to_stage.get(agent_id, agent_id) not in stages_to_run
        ]

    async def _stream():
        pipeline_results: list[dict] = []
        total = len(pipeline)
        with _capture_logs_for_sse() as log_queue:
            logger.info("[Generate] Running %d agents", total)

            for agent_id, agent_label in skipped_agents:
                yield _sse_event(
                    {
                        "agent_id": agent_id,
                        "agent_label": agent_label,
                        "state": "skipped",
                        "cached": True,
                    }
                )
                pipeline_results.append(
                    {
                        "agent_id": agent_id,
                        "agent_label": agent_label,
                        "status": "skipped",
                        "result": "Cached — skipped",
                    }
                )

            for idx, (agent_id, agent_label, run_fn) in enumerate(pipeline):
                async for event in _run_pipeline_stage(
                    agent_id,
                    agent_label,
                    idx,
                    total,
                    run_fn,
                    log_queue,
                    pipeline_results,
                    logger,
                ):
                    yield event

            final_status = (
                "ok" if all(result["status"] in {"ok", "skipped"} for result in pipeline_results) else "partial"
            )
            logger.info("[Generate] Done — status=%s", final_status)
            for event in _drain_log_queue(log_queue):
                yield event

            if run_id and manifest is not None:
                try:
                    history = get_history_fn()
                    for pipeline_result in pipeline_results:
                        if pipeline_result["status"] != "ok":
                            continue
                        stage_name = agent_to_stage.get(pipeline_result["agent_id"])
                        if not stage_name:
                            continue
                        history.update_stage(
                            manifest,
                            stage_name,
                            status=StageStatus.COMPLETED,
                            deterministic=STAGE_GRAPH.get(
                                stage_name,
                                type("Stage", (), {"deterministic": True}),
                            ).deterministic,
                        )
                        agent_dir = stage_to_agent_dir.get(stage_name)
                        if agent_dir:
                            history.store_artifacts(manifest, agent_dir)
                    ran = {
                        agent_to_stage.get(pipeline_result["agent_id"])
                        for pipeline_result in pipeline_results
                        if pipeline_result["status"] == "ok" and agent_to_stage.get(pipeline_result["agent_id"])
                    }
                    if ran:
                        history.mark_overwritten(workbook_name, ran, exclude_run_id=manifest.run_id)
                    history.cleanup_old_runs(workbook_name)
                except Exception as exc:
                    logger.warning("Run history finalize failed: %s", exc)

            yield _sse_event(
                {
                    "state": "complete",
                    "status": final_status,
                    "pipeline_results": pipeline_results,
                }
            )

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
