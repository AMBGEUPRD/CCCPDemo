"""Shared runtime helpers for the FastAPI web application."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import time
import traceback
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from datetime import datetime, timezone

from Tableau2PowerBI.core.logging_setup import shorten_abs_paths

RESULT_TTL_SECONDS = 60 * 60
_MAX_RESULTS = 200
_result_store: dict[str, tuple[float, str]] = {}


def _evict_expired() -> None:
    """Remove expired entries from the in-memory result store."""
    cutoff = time.time() - RESULT_TTL_SECONDS
    expired = [key for key, (timestamp, _) in _result_store.items() if timestamp < cutoff]
    for key in expired:
        _result_store.pop(key, None)


def store_result(result_id: str, payload: str) -> None:
    """Persist a result payload in the in-memory store."""
    _evict_expired()
    if len(_result_store) >= _MAX_RESULTS:
        oldest = min(_result_store, key=lambda key: _result_store[key][0])
        _result_store.pop(oldest, None)
    _result_store[result_id] = (time.time(), payload)


def _sse_event(data: dict, event: str | None = None) -> str:
    """Format one server-sent event payload."""
    payload = json.dumps(data, ensure_ascii=False)
    lines = ""
    if event:
        lines += f"event: {event}\n"
    lines += f"data: {payload}\n\n"
    return lines


class _SSELogHandler(logging.Handler):
    """Capture log records into a queue for SSE streaming."""

    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self._queue = log_queue
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sub_agent = getattr(record, "sub_agent", None)
            if sub_agent and isinstance(sub_agent, dict):
                self._queue.put_nowait(
                    {
                        "type": "sub_agent",
                        **sub_agent,
                        "message": shorten_abs_paths(self.format(record)),
                    }
                )
            else:
                self._queue.put_nowait(
                    {
                        "type": "log",
                        "level": record.levelname,
                        "message": shorten_abs_paths(self.format(record)),
                        "logger": record.name,
                    }
                )
        except queue.Full:
            pass


def _drain_log_queue(log_queue: queue.Queue) -> list[str]:
    """Convert all queued log records into SSE messages."""
    events: list[str] = []
    while True:
        try:
            record = log_queue.get_nowait()
        except queue.Empty:
            break
        events.append(_sse_event(record))
    return events


async def _run_with_logs(
    run_fn,
    log_queue: queue.Queue,
    results: list,
    poll_interval: float = 0.1,
) -> AsyncGenerator[str, None]:
    """Run a sync function in an executor while streaming queued logs."""
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, run_fn)

    while not future.done():
        await asyncio.sleep(poll_interval)
        for event in _drain_log_queue(log_queue):
            yield event

    for event in _drain_log_queue(log_queue):
        yield event

    results.append(future.result())


async def _run_pipeline_stage(
    agent_id: str,
    agent_label: str,
    idx: int,
    total: int,
    run_fn,
    log_queue: queue.Queue,
    pipeline_results: list[dict],
    logger: logging.Logger,
) -> AsyncGenerator[str, None]:
    """Run one sequential pipeline stage and emit SSE status updates."""
    yield _sse_event(
        {
            "agent_id": agent_id,
            "agent_label": agent_label,
            "index": idx,
            "total": total,
            "state": "running",
        }
    )
    logger.info("Running %s…", agent_label)

    try:
        holder: list = []
        async for event in _run_with_logs(run_fn, log_queue, holder):
            yield event
        result = holder[0]
        pipeline_results.append(
            {
                "agent_id": agent_id,
                "agent_label": agent_label,
                "status": "ok",
                "result": _format_pipeline_result_for_display(result),
            }
        )
        yield _sse_event(
            {
                "agent_id": agent_id,
                "index": idx,
                "total": total,
                "state": "done",
            }
        )
        logger.info("%s completed", agent_label)
        for event in _drain_log_queue(log_queue):
            yield event
    except Exception as exc:
        logger.error("%s failed: %s\n%s", agent_label, exc, traceback.format_exc())
        for event in _drain_log_queue(log_queue):
            yield event
        pipeline_results.append(
            {
                "agent_id": agent_id,
                "agent_label": agent_label,
                "status": "error",
                "result": str(exc),
            }
        )
        yield _sse_event(
            {
                "agent_id": agent_id,
                "index": idx,
                "total": total,
                "state": "error",
                "message": str(exc),
            }
        )


@contextmanager
def _capture_logs_for_sse(min_level: int = logging.DEBUG):
    """Create a log queue and attach a handler to capture logs for SSE streaming.

    Usage:
        with _capture_logs_for_sse() as log_queue:
            # run code that logs
            ...
    """
    log_queue: queue.Queue = queue.Queue(maxsize=1000)
    handler = _SSELogHandler(log_queue)
    handler.setLevel(min_level)

    # Attach to the root logger to capture all logs.
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        yield log_queue
    finally:
        root_logger.removeHandler(handler)


def _format_pipeline_result_for_display(result: object) -> str:
    """Normalize endpoint results into displayable strings."""
    if result is None:
        return "Analysis completed."
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


def _iso_now() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()
