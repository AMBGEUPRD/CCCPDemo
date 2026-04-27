"""Base Agent class for the Azure AI Foundry pipeline.

Every pipeline agent extends :class:`Agent`, which handles:

- Loading the agent's SKILL.md prompt from ``agents/<folder>/SKILL.md``
- Orchestrating LLM calls via a pluggable :class:`ModelBackend`
- Retry logic (rate-limit, timeout, circuit breaker)
- Prompt-size logging and usage tracking

The backend abstraction means agents are model-agnostic: the same
``Agent`` subclass can use GPT-5.4 (Responses API) or Claude Opus 4.6
(Chat Completions API) — switching is purely a config change.

Typical subclass pattern::

    class MyAgent(Agent):
        def __init__(self, settings=None):
            super().__init__(skill_name="my_agent", settings=settings)

        def do_work(self, prompt: str) -> str:
            return self.run(prompt)

The ``run()`` method is the main entry point: it initialises the
backend (idempotent), sends the prompt, and returns the response text.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Any, Callable

from Tableau2PowerBI.core.agent.semaphores import (
    get_async_llm_semaphore,
    get_llm_semaphore,
)
from Tableau2PowerBI.core.agent.validation import run_with_validation as run_with_validation_helper
from Tableau2PowerBI.core.agent.validation import run_with_validation_async as run_with_validation_async_helper
from Tableau2PowerBI.core.backends import (
    LLMResponse,
    ModelBackend,
    create_backend,
)
from Tableau2PowerBI.core.config import AgentSettings, get_agent_settings
from Tableau2PowerBI.core.token_tracker import token_tracker


class ContextLengthExceededError(Exception):
    """The prompt exceeded the model's context window."""

    def __init__(self, prompt_size_bytes: int):
        self.prompt_size_bytes = prompt_size_bytes
        super().__init__(f"Prompt ({prompt_size_bytes / 1024:.1f} KB) exceeds context window.")


# Maps each agent's skill_name (Azure identifier) to its package folder
# under agents/. Skill_names are fixed — they drive Azure AI Foundry
# agent naming, output directories, and logger names.

_SKILL_FOLDER_MAP: dict[str, str] = {
    "tableau_metadata_extractor_agent": "metadata_extractor",
    "powerbi_metadata_extractor_agent": "powerbi_metadata_extractor",
    "pbip_project_skeleton_agent": "skeleton",
    "pbip_semantic_model_generator_agent": "semantic_model",
    "tmdl_measures_generator_agent": "dax_measures",
    "pbir_report_generator_agent": "report_visuals",
    "report_skeleton_agent": "report_skeleton",
    "report_page_visuals_agent": "report_page_visuals",
    "pbip_project_assembler_agent": "assembler",
    "warnings_reviewer_agent": "warnings_reviewer",
    "tableau_functional_doc_agent": "functional_doc",
    "target_technical_doc_agent": "target_technical_doc",
}


def load_skill(name: str) -> str:
    """Read the SKILL.md prompt for the given agent.

    Skills are collocated with their agent code at
    ``src/Tableau2PowerBI/agents/<folder>/SKILL.md``.
    The ``name`` parameter is the agent's ``skill_name``, which is
    mapped to the folder via :data:`_SKILL_FOLDER_MAP`.
    """
    package_root = Path(__file__).resolve().parent.parent.parent
    folder = _SKILL_FOLDER_MAP.get(name, name)
    skill_path = package_root / "agents" / folder / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")
    return skill_path.read_text(encoding="utf-8")


class Agent:
    """Base class for all pipeline agents.

    Each agent wraps an LLM call with a SKILL.md system prompt.
    Subclasses typically add domain-specific methods that build a
    prompt, call ``self.run(prompt)``, and process the result.

    The actual API interaction is delegated to a :class:`ModelBackend`,
    which is selected based on the model name and the ``model_backends``
    mapping in :class:`AgentSettings`.
    """

    def __init__(
        self,
        skill_name: str,
        model: str | None = None,
        settings: AgentSettings | None = None,
        skill_loader: Callable[[str], str] = load_skill,
        backend: ModelBackend | None = None,
    ) -> None:
        """Initialise the agent.

        This only loads the skill text and sets up configuration.
        No remote resources are created until :meth:`run` is called.

        Args:
            skill_name: Identifies the SKILL.md file and the agent name.
            model: Model override (highest precedence).  Falls back to
                per-agent config, then ``settings.default_model``.
            settings: Pipeline configuration; uses defaults if ``None``.
            skill_loader: Callable that returns the skill prompt text.
            backend: Explicit backend override (e.g. ``MockBackend``
                for testing).  If ``None``, auto-resolved from model.
        """
        self.skill_name = skill_name
        self.agent_name = f"agent-{skill_name.replace('_', '-')}"
        self.settings = settings or get_agent_settings()

        # Model resolution: explicit arg > per-agent config > default
        self.model = model or self.settings.get_model_for_agent(skill_name)

        self.skill_text = skill_loader(skill_name)
        self.logger = logging.getLogger(f"Tableau2PowerBI.{skill_name}")

        # Backend resolution: explicit arg > auto from model_backends
        if backend is not None:
            self.backend: ModelBackend = backend
        else:
            backend_type = self.settings.get_backend_for_model(self.model)
            self.backend = create_backend(backend_type)

        self._consecutive_failures: int = 0
        self._backend_initialized: bool = False

    # ── Backward-compatible no-op ──────────────────────────────────────────

    def create(self) -> "Agent":
        """No-op kept for backward compatibility.

        Backend initialisation now happens lazily on the first
        ``run()`` call via ``_ensure_backend()``.  Existing callers
        (CLI, webapp, sub-agents) can continue to call ``create()``
        without changes.
        """
        return self

    # ── Backend lifecycle ──────────────────────────────────────────────────

    def _ensure_backend(self) -> None:
        """Initialise the backend if not already done (idempotent)."""
        if self._backend_initialized:
            return
        self.backend.initialize(
            settings=self.settings,
            model=self.model,
            skill_text=self.skill_text,
            agent_name=self.agent_name,
            logger=self.logger,
        )
        self._backend_initialized = True
        self.logger.info(
            "Backend ready model=%s backend=%s",
            self.model,
            type(self.backend).__name__,
        )

    # ── Prompt logging ─────────────────────────────────────────────────────

    def _log_prompt_size(self, prompt: str) -> None:
        """Log the prompt size in KB; warn if it exceeds the threshold."""
        prompt_kb = len(prompt.encode("utf-8")) / 1024
        self.logger.info("Prompt size: %.1f KB", prompt_kb)

        if prompt_kb > self.settings.prompt_warning_kb:
            self.logger.warning(
                "Large prompt (%.1f KB). " "Consider trimming the input payload.",
                prompt_kb,
            )

    # ── Resilience helpers ───────────────────────────────────────────────

    @staticmethod
    def _is_context_length_exceeded(exc: Exception) -> bool:
        """Check if the exception signals a context-length-exceeded error.

        Works with OpenAI SDK exceptions (``code`` attribute) and
        generic HTTP errors (``body`` dict with a ``code`` key).
        """
        # OpenAI SDK: exc.code == "context_length_exceeded"
        if getattr(exc, "code", None) == "context_length_exceeded":
            return True
        # Fallback: body dict with code key (some SDK versions)
        body = getattr(exc, "body", None)
        if isinstance(body, dict) and body.get("code") == "context_length_exceeded":
            return True
        return False

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter for attempt N (0-indexed).

        Formula: base * 2^attempt + uniform jitter in [0, base).
        """
        base = self.settings.rate_limit_base_delay_seconds
        delay = base * (2**attempt) + random.uniform(0, base)
        return delay

    def _check_circuit_breaker(self) -> None:
        """Raise if too many consecutive failures have occurred."""
        if self._consecutive_failures >= self.settings.circuit_breaker_threshold:
            raise RuntimeError(
                f"Circuit breaker open after "
                f"{self._consecutive_failures} consecutive failures. "
                "Inspect logs and retry after resolving the root cause."
            )

    def _record_success(self) -> None:
        """Reset the consecutive failure counter on success."""
        self._consecutive_failures = 0

    def _record_failure(self) -> None:
        """Increment the consecutive failure counter."""
        self._consecutive_failures += 1

    @staticmethod
    def _parse_retry_after(exc: Exception) -> float | None:
        """Extract Retry-After from a 429 exception, if present.

        Works with both ``openai.RateLimitError`` (Responses API) and
        generic HTTP exceptions (Chat Completions API) — both expose
        ``exc.response.headers``.
        """
        response = getattr(exc, "response", None)
        if response is None:
            return None
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after is None:
            return None
        try:
            return float(retry_after)
        except (ValueError, TypeError):
            return None

    # ── run ────────────────────────────────────────────────────────────────

    def run(self, prompt: str, **kwargs: Any) -> str:
        """Send *prompt* to the LLM and return the full response text.

        Handles:
        - Concurrency gating via a process-wide semaphore
        - Circuit breaking: raises immediately if consecutive failures
          exceed the configured threshold
        - Rate-limit retry: backs off exponentially on HTTP 429
        - Timeout retry: retries once on ``TimeoutError``
        - Success/failure tracking for the circuit breaker

        Any extra ``kwargs`` are accepted for backward compatibility
        (e.g. ``force_new_conversation``), but are no longer used — each
        backend call is stateless by default.
        """
        self._check_circuit_breaker()
        self._ensure_backend()
        self._log_prompt_size(prompt)
        sem = get_llm_semaphore(self.settings.max_concurrent_llm_calls)

        for rate_attempt in range(self.settings.rate_limit_max_retries + 1):
            try:
                with sem:
                    response: LLMResponse = self.backend.call(prompt)
                self._record_success()
                token_tracker.record(
                    self.skill_name,
                    response.tokens_in,
                    response.tokens_out,
                )
                self.logger.info(
                    "run() completed elapsed=%.1fs " "tokens_in=%d tokens_out=%d",
                    response.elapsed_seconds,
                    response.tokens_in,
                    response.tokens_out,
                )
                return response.text
            except TimeoutError:
                if rate_attempt == 0:
                    self.logger.warning(
                        "Timeout on attempt %d — retrying once.",
                        rate_attempt + 1,
                    )
                    continue
                self._record_failure()
                raise
            except Exception as exc:
                # Context-length exceeded: surface immediately, skip
                # circuit breaker — caller decides how to truncate.
                if self._is_context_length_exceeded(exc):
                    prompt_bytes = len(prompt.encode("utf-8"))
                    raise ContextLengthExceededError(prompt_bytes) from exc

                status = getattr(exc, "status_code", None)
                if status == 429:
                    retry_after = self._parse_retry_after(exc)
                    delay = retry_after or self._backoff_delay(rate_attempt)
                    self.logger.warning(
                        "Rate limited (429). Waiting %.1fs " "before retry %d/%d.",
                        delay,
                        rate_attempt + 1,
                        self.settings.rate_limit_max_retries,
                    )
                    time.sleep(delay)
                    if rate_attempt < self.settings.rate_limit_max_retries:
                        continue
                self._record_failure()
                raise

        # Should not be reached, but satisfies the type checker.
        self._record_failure()
        raise RuntimeError("run() exhausted all retry attempts")

    # ── close ──────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Release the backend's SDK clients and connections."""
        self.backend.close()

    # ── context manager ────────────────────────────────────────────────────

    def __enter__(self) -> Agent:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # ── async run ──────────────────────────────────────────────────────────

    async def run_async(self, prompt: str, **kwargs: Any) -> str:
        """Async version of :meth:`run`.

        Same contract as ``run()`` but uses ``call_async()`` on the
        backend and ``asyncio.Semaphore`` for concurrency gating so no
        threads are blocked.

        The backend is still initialised synchronously (one-off cost)
        because Azure agent registration is a cheap CRUD call.
        """
        self._check_circuit_breaker()
        self._ensure_backend()
        self._log_prompt_size(prompt)
        sem = get_async_llm_semaphore(
            self.settings.max_concurrent_llm_calls,
        )

        for rate_attempt in range(self.settings.rate_limit_max_retries + 1):
            try:
                async with sem:
                    response: LLMResponse = await self.backend.call_async(
                        prompt,
                    )
                self._record_success()
                token_tracker.record(
                    self.skill_name,
                    response.tokens_in,
                    response.tokens_out,
                )
                self.logger.info(
                    "run_async() completed elapsed=%.1fs " "tokens_in=%d tokens_out=%d",
                    response.elapsed_seconds,
                    response.tokens_in,
                    response.tokens_out,
                )
                return response.text
            except TimeoutError:
                if rate_attempt == 0:
                    self.logger.warning(
                        "Timeout on attempt %d — retrying once.",
                        rate_attempt + 1,
                    )
                    continue
                self._record_failure()
                raise
            except Exception as exc:
                # Context-length exceeded: surface immediately, skip
                # circuit breaker — caller decides how to truncate.
                if self._is_context_length_exceeded(exc):
                    prompt_bytes = len(prompt.encode("utf-8"))
                    raise ContextLengthExceededError(prompt_bytes) from exc

                status = getattr(exc, "status_code", None)
                if status == 429:
                    retry_after = self._parse_retry_after(exc)
                    delay = retry_after or self._backoff_delay(rate_attempt)
                    self.logger.warning(
                        "Rate limited (429). Waiting %.1fs " "before retry %d/%d.",
                        delay,
                        rate_attempt + 1,
                        self.settings.rate_limit_max_retries,
                    )
                    await asyncio.sleep(delay)
                    if rate_attempt < self.settings.rate_limit_max_retries:
                        continue
                self._record_failure()
                raise

        self._record_failure()
        raise RuntimeError("run_async() exhausted all retry attempts")

    # ── async context manager ──────────────────────────────────────────────

    async def __aenter__(self) -> Agent:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        self.close()

    # ── shared response validation helpers ────────────────────────────────

    def run_with_validation(
        self,
        prompt: str,
        parser,
        *,
        label: str,
        parse_exceptions: tuple[type[Exception], ...] = (ValueError,),
        error_formatter: Callable[[Exception], str] | None = None,
    ):
        """Run an LLM prompt with parser validation and feedback retries."""
        return run_with_validation_helper(
            prompt,
            parser,
            label=label,
            max_retries=self.settings.max_validation_retries,
            run_call=lambda current_prompt, is_first: self.run(
                current_prompt,
                force_new_conversation=is_first,
            ),
            logger=self.logger,
            parse_exceptions=parse_exceptions,
            error_formatter=error_formatter,
        )

    async def run_with_validation_async(
        self,
        prompt: str,
        parser,
        *,
        label: str,
        parse_exceptions: tuple[type[Exception], ...] = (ValueError,),
        error_formatter: Callable[[Exception], str] | None = None,
    ):
        """Async version of :meth:`run_with_validation`."""
        return await run_with_validation_async_helper(
            prompt,
            parser,
            label=label,
            max_retries=self.settings.max_validation_retries,
            run_call=lambda current_prompt, is_first: self.run_async(
                current_prompt,
                force_new_conversation=is_first,
            ),
            logger=self.logger,
            parse_exceptions=parse_exceptions,
            error_formatter=error_formatter,
        )
