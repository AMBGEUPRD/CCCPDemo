"""Pipeline-wide token usage tracker.

Provides a lightweight, thread-safe counter that accumulates
``tokens_in`` / ``tokens_out`` across all LLM calls in a pipeline
run.  Agents call :func:`record` after every successful backend
response; the pipeline calls :func:`summary` at the end to log
totals.

Usage::

    from Tableau2PowerBI.core.token_tracker import token_tracker

    # Inside Agent.run() — already wired automatically
    token_tracker.record("semantic_model", tokens_in=80_000, tokens_out=4_000)

    # At pipeline end
    token_tracker.log_summary()
    token_tracker.reset()
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class _AgentUsage:
    """Accumulated usage for a single agent (or skill_name)."""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


class TokenTracker:
    """Thread-safe accumulator for LLM token usage across a pipeline run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._agents: dict[str, _AgentUsage] = {}

    # ── Recording ──────────────────────────────────────────────────────

    def record(
        self,
        agent_name: str,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        """Add one LLM call's usage to the running totals."""
        with self._lock:
            usage = self._agents.setdefault(agent_name, _AgentUsage())
            usage.calls += 1
            usage.tokens_in += tokens_in
            usage.tokens_out += tokens_out

    # ── Reporting ──────────────────────────────────────────────────────

    def summary(self) -> dict[str, dict[str, int]]:
        """Return a snapshot: ``{agent_name: {calls, tokens_in, tokens_out}}``."""
        with self._lock:
            return {
                name: {
                    "calls": u.calls,
                    "tokens_in": u.tokens_in,
                    "tokens_out": u.tokens_out,
                }
                for name, u in sorted(self._agents.items())
            }

    def total_tokens_in(self) -> int:
        """Sum of input tokens across all agents."""
        with self._lock:
            return sum(u.tokens_in for u in self._agents.values())

    def total_tokens_out(self) -> int:
        """Sum of output tokens across all agents."""
        with self._lock:
            return sum(u.tokens_out for u in self._agents.values())

    def log_summary(self) -> None:
        """Log a formatted per-agent and grand-total summary."""
        data = self.summary()
        if not data:
            logger.info("Token usage: no LLM calls recorded")
            return

        logger.info("═══ Token Usage Summary ═══")
        grand_in = 0
        grand_out = 0
        for name, u in data.items():
            logger.info(
                "  %-40s calls=%d  in=%7d  out=%6d",
                name,
                u["calls"],
                u["tokens_in"],
                u["tokens_out"],
            )
            grand_in += u["tokens_in"]
            grand_out += u["tokens_out"]
        logger.info(
            "  %-40s          in=%7d  out=%6d",
            "TOTAL",
            grand_in,
            grand_out,
        )

    def reset(self) -> None:
        """Clear all accumulated data (call between pipeline runs)."""
        with self._lock:
            self._agents.clear()


# Module-level singleton — shared by all agents in the process.
token_tracker = TokenTracker()
