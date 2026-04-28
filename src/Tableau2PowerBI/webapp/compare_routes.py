"""SSE streaming response builder for the FDD comparison pipeline."""

from __future__ import annotations

import logging
import traceback

from fastapi.responses import StreamingResponse

from Tableau2PowerBI.webapp.runtime import (
    _capture_logs_for_sse,
    _drain_log_queue,
    _run_with_logs,
    _sse_event,
)


async def build_compare_stream_response(
    fdd_docs: dict[str, str],
    *,
    compare_agent_cls,
    logger: logging.Logger,
) -> StreamingResponse:
    """Build a StreamingResponse that runs the FDD comparison agent and emits SSE events.

    Follows the same pattern as build_documentation_stream_response in documentation_routes.py:
    _capture_logs_for_sse → _run_with_logs (executor) → _drain_log_queue → complete/error event.

    Args:
        fdd_docs: Mapping of workbook_name → FDD markdown text (≥ 2 entries).
        compare_agent_cls: The FDDCompareAgent class (injected for testability).
        logger: Caller's logger for top-level error messages.
    """
    n = len(fdd_docs)
    names = list(fdd_docs.keys())

    async def _stream():
        with _capture_logs_for_sse() as log_queue:
            try:
                yield _sse_event({
                    "state": "running",
                    "label": f"Comparing {n} report{'s' if n != 1 else ''}…",
                    "agent_id": "fdd_compare",
                    "agent_label": "FDD Comparison",
                })
                logger.info("[Compare] Starting comparison of: %s", ", ".join(names))

                def _run():
                    agent = compare_agent_cls()
                    return agent.compare(fdd_docs)

                holder: list = []
                async for event in _run_with_logs(_run, log_queue, holder):
                    yield event

                result = holder[0]
                for event in _drain_log_queue(log_queue):
                    yield event

                logger.info("[Compare] Comparison complete — %d groups", len(result.groups))
                yield _sse_event({
                    "state": "complete",
                    "result": result.model_dump(),
                })

            except Exception as exc:
                logger.error("[Compare] Failed: %s\n%s", exc, traceback.format_exc())
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
