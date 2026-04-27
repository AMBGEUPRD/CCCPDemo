"""Large streaming route implementations extracted from webapp.app."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from Tableau2PowerBI.core.run_history import STAGE_GRAPH, StageStatus
from Tableau2PowerBI.core.utils import get_output_dir
from Tableau2PowerBI.webapp.runtime import (
    _capture_logs_for_sse,
    _coerce,
    _drain_log_queue,
    _iso_now,
    _run_pipeline_stage,
    _run_with_logs,
    _sse_event,
    store_result,
)

PipelineTask = tuple[str, str, Callable[[], str]]
IndexedPipelineTask = tuple[int, PipelineTask]


def _partition_pipeline_phase3(
    pipeline: list[PipelineTask],
    phase3_ids: set[str],
) -> tuple[list[IndexedPipelineTask], list[IndexedPipelineTask], list[IndexedPipelineTask]]:
    """Split pipeline stages into pre-phase3, phase3-parallel, and post-phase3 segments."""
    parallel = [(index, item) for index, item in enumerate(pipeline) if item[0] in phase3_ids]
    if not parallel:
        return list(enumerate(pipeline)), [], []

    p3_min = min(index for index, _ in parallel)
    p3_max = max(index for index, _ in parallel)
    pre_parallel = [
        (index, item) for index, item in enumerate(pipeline) if item[0] not in phase3_ids and index < p3_min
    ]
    post_parallel = [
        (index, item) for index, item in enumerate(pipeline) if item[0] not in phase3_ids and index > p3_max
    ]
    return pre_parallel, parallel, post_parallel


async def _run_parallel_phase3(
    parallel: list[IndexedPipelineTask],
    *,
    total: int,
    log_queue,
    pipeline_results: list[dict],
    logger: logging.Logger,
) -> Any:
    """Run phase-3 agents concurrently and stream progress events."""
    if not parallel:
        return

    for idx, (agent_id, agent_label, _run_fn) in parallel:
        yield _sse_event(
            {
                "agent_id": agent_id,
                "agent_label": agent_label,
                "index": idx,
                "total": total,
                "state": "running",
            }
        )

    def _run_phase3_agent(agent_id: str, label: str, run_fn: Callable[[], str]) -> tuple[str, str, str]:
        try:
            result = run_fn()
            return agent_id, "ok", result
        except Exception as exc:
            logger.error("%s failed: %s", label, exc)
            return agent_id, "error", str(exc)

    parallel_info: dict[str, tuple[int, str]] = {
        agent_id: (idx, agent_label) for idx, (agent_id, agent_label, _run_fn) in parallel
    }

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_run_phase3_agent, agent_id, agent_label, run_fn): agent_id
            for _idx, (agent_id, agent_label, run_fn) in parallel
        }
        done_futures: set = set()
        while len(done_futures) < len(futures):
            await asyncio.sleep(0.3)
            for event in _drain_log_queue(log_queue):
                yield event

            for future in list(futures):
                if not future.done() or future in done_futures:
                    continue

                done_futures.add(future)
                agent_id, status, result = future.result()
                p_idx, p_label = parallel_info[agent_id]
                if status == "ok":
                    pipeline_results.append(
                        {
                            "agent_id": agent_id,
                            "agent_label": p_label,
                            "status": "ok",
                            "result": _coerce(result),
                        }
                    )
                    yield _sse_event(
                        {
                            "agent_id": agent_id,
                            "index": p_idx,
                            "total": total,
                            "state": "done",
                        }
                    )
                    continue

                error_msg = str(result)
                pipeline_results.append(
                    {
                        "agent_id": agent_id,
                        "agent_label": p_label,
                        "status": "error",
                        "result": error_msg,
                    }
                )
                yield _sse_event(
                    {
                        "agent_id": agent_id,
                        "index": p_idx,
                        "total": total,
                        "state": "error",
                        "message": error_msg,
                    }
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
                coerced = _coerce(result)

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
    target_technical_doc_cls,
    skeleton_agent_cls,
    semantic_model_agent_cls,
    dax_measures_agent_cls,
    report_visuals_agent_cls,
    assembler_agent_cls,
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
    semantic_model_name = body.get("semantic_model_name", "")
    skip_tdd = body.get("skip_tdd", False)
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
    semantic_model_name = semantic_model_name or workbook_name

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
                "target_technical_doc",
                "skeleton",
                "semantic_model",
                "dax_measures",
                "report_visuals",
                "assembler",
            }
            stages_to_run = resolve_stages_to_run_fn(
                manifest,
                current_hashes={
                    "metadata_extractor": compute_input_hash_fn(
                        [Path("data/input") / (manifest.workbook_file or Path(twb_path).name)]
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
                    "skeleton": compute_input_hash_fn([Path(twb_path)]),
                    "semantic_model": compute_input_hash_fn(
                        [get_output_dir("target_technical_doc_agent", workbook_name)]
                    ),
                    "dax_measures": compute_input_hash_fn(
                        [get_output_dir("target_technical_doc_agent", workbook_name)]
                    ),
                    "report_visuals": compute_input_hash_fn(
                        [get_output_dir("target_technical_doc_agent", workbook_name)]
                    ),
                    "assembler": compute_input_hash_fn(
                        [
                            get_output_dir("pbip_project_skeleton_agent", workbook_name),
                            get_output_dir("pbip_semantic_model_generator_agent", workbook_name),
                            get_output_dir("tmdl_measures_generator_agent", workbook_name),
                            get_output_dir("pbir_report_generator_agent", workbook_name),
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

    def _run_skeleton() -> str:
        agent = skeleton_agent_cls()
        output = agent.generate_pbip_project_skeleton(
            workbook_name,
            report_name=workbook_name,
            semantic_model_name=semantic_model_name,
        )
        return str(output)

    def _run_semantic_model() -> str:
        agent = semantic_model_agent_cls()
        agent.create()
        agent.generate_pbip_semantic_model(workbook_name, semantic_model_name=semantic_model_name)
        return "Semantic model generated."

    def _run_dax_measures() -> str:
        agent = dax_measures_agent_cls()
        agent.create()
        agent.generate_tmdl_measures(workbook_name)
        return "DAX measures generated."

    def _run_visuals() -> str:
        agent = report_visuals_agent_cls()
        agent.create()
        agent.generate_pbir_report(workbook_name)
        return "Visuals / report generated."

    def _run_assembler() -> str:
        agent = assembler_agent_cls()
        output = agent.assemble_pbip_project(workbook_name)
        return str(output)

    pipeline = [
        ("tableau_metadata_extractor", "Metadata Extraction", _run_metadata_extractor),
        ("target_technical_doc", "Technical Design Document", _run_tdd),
        ("pbip_project_skeleton", "Project Skeleton", _run_skeleton),
        ("pbip_semantic_model_generator", "Semantic Model Generator", _run_semantic_model),
        ("pbip_dax_generator", "DAX Generator", _run_dax_measures),
        ("pbip_visuals_generator", "Visuals Generator", _run_visuals),
        ("pbip_project_assembler", "Project Assembler", _run_assembler),
    ]

    agent_to_stage = {
        "tableau_metadata_extractor": "metadata_extractor",
        "target_technical_doc": "target_technical_doc",
        "pbip_project_skeleton": "skeleton",
        "pbip_semantic_model_generator": "semantic_model",
        "pbip_dax_generator": "dax_measures",
        "pbip_visuals_generator": "report_visuals",
        "pbip_project_assembler": "assembler",
    }
    stage_to_agent_dir = {
        "metadata_extractor": "tableau_metadata_extractor_agent",
        "target_technical_doc": "target_technical_doc_agent",
        "skeleton": "pbip_project_skeleton_agent",
        "semantic_model": "pbip_semantic_model_generator_agent",
        "dax_measures": "tmdl_measures_generator_agent",
        "report_visuals": "pbir_report_generator_agent",
        "assembler": "pbip_project_assembler_agent",
    }

    if skip_tdd:
        pipeline = [
            (agent_id, agent_label, run_fn)
            for agent_id, agent_label, run_fn in pipeline
            if agent_id not in ("target_technical_doc", "tableau_metadata_extractor")
        ]

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

    phase3_ids = {
        "pbip_semantic_model_generator",
        "pbip_dax_generator",
        "pbip_visuals_generator",
    }

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

            pre_parallel, parallel, post_parallel = _partition_pipeline_phase3(pipeline, phase3_ids)

            for idx, (agent_id, agent_label, run_fn) in pre_parallel:
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

            logger.info("[Phase 3] Running %d agents in parallel", len(parallel))
            async for event in _run_parallel_phase3(
                parallel,
                total=total,
                log_queue=log_queue,
                pipeline_results=pipeline_results,
                logger=logger,
            ):
                yield event

            for event in _drain_log_queue(log_queue):
                yield event

            for idx, (agent_id, agent_label, run_fn) in post_parallel:
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
