"""Shared semaphore primitives for global LLM concurrency limits."""

from __future__ import annotations

import asyncio
import threading

# Process-wide semaphore limiting concurrent sync LLM calls.
_llm_semaphore: threading.Semaphore | None = None
_sem_lock = threading.Lock()

# Async counterpart, keyed by event loop to avoid cross-loop errors.
_async_semaphores: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def get_llm_semaphore(max_calls: int = 4) -> threading.Semaphore:
    """Return (or create) the process-wide sync LLM semaphore."""
    global _llm_semaphore
    if _llm_semaphore is None:
        with _sem_lock:
            if _llm_semaphore is None:
                _llm_semaphore = threading.Semaphore(max_calls)
    return _llm_semaphore


def get_async_llm_semaphore(max_calls: int = 4) -> asyncio.Semaphore:
    """Return (or create) the async LLM semaphore for the running loop.

    Keyed by event-loop object so separate loops (e.g. in tests) each
    get their own semaphore and never raise cross-loop errors.
    """
    loop = asyncio.get_running_loop()
    sem = _async_semaphores.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(max_calls)
        _async_semaphores[loop] = sem
    return sem
