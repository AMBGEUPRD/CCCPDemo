"""Tests for the Agent base class (orchestration, resilience, backend delegation).

The Agent no longer owns API interaction — that lives in backends.
These tests use MockBackend to verify orchestration logic without
mocking Azure SDK internals.
"""

import asyncio
import unittest
from types import SimpleNamespace

from Tableau2PowerBI.core.agent import Agent
from Tableau2PowerBI.core.agent.base import ContextLengthExceededError
from Tableau2PowerBI.core.backends import MockBackend
from Tableau2PowerBI.core.config import AgentSettings

# ── _StubAgent: injects a MockBackend via the constructor ─────────────────


class _StubAgent(Agent):
    """Agent subclass for testing — uses a pre-built MockBackend."""

    def __init__(
        self,
        *,
        settings: AgentSettings,
        backend: MockBackend,
        model: str | None = None,
    ):
        super().__init__(
            skill_name="pbip_semantic_model_generator_agent",
            settings=settings,
            model=model,
            backend=backend,
        )


# ── Helper ────────────────────────────────────────────────────────────────


class _HttpError(Exception):
    """Exception with status_code and response attributes for testing."""

    def __init__(self, message: str, status_code: int, headers: dict | None = None):
        super().__init__(message, status_code, headers)
        self.status_code = status_code
        self.response = SimpleNamespace(headers=headers or {})


class _ContextLengthError(Exception):
    """Simulates an OpenAI SDK context_length_exceeded error."""

    def __init__(self):
        super().__init__("context_length_exceeded")
        self.status_code = 400
        self.code = "context_length_exceeded"


def _make_settings(**overrides) -> AgentSettings:
    return AgentSettings(
        project_endpoint="https://example.test",
        **overrides,
    )


# ── Tests ────────────────────────────────────────────────────────────────


class AgentConstructorTests(unittest.TestCase):
    def test_constructor_loads_skill_text(self):
        backend = MockBackend()
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        self.assertIn("PBIP Semantic Model", agent.skill_text)

    def test_constructor_uses_explicit_model_over_config(self):
        """Explicit model= arg takes highest precedence."""
        backend = MockBackend()
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
            model="my-override",
        )
        self.assertEqual(agent.model, "my-override")

    def test_constructor_uses_per_agent_model_from_settings(self):
        """Per-agent config field takes precedence over default_model."""
        backend = MockBackend()
        settings = _make_settings(model_semantic_model="gpt-5.4")
        agent = _StubAgent(
            settings=settings,
            backend=backend,
        )
        self.assertEqual(agent.model, "gpt-5.4")

    def test_constructor_falls_back_to_default_model(self):
        """Unknown agents fall back to default_model."""
        backend = MockBackend()
        agent = Agent(
            skill_name="some_unknown_agent",
            settings=_make_settings(default_model="fallback-model"),
            backend=backend,
            skill_loader=lambda _: "test skill",
        )
        self.assertEqual(agent.model, "fallback-model")

    def test_backend_is_injected(self):
        backend = MockBackend()
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        self.assertIs(agent.backend, backend)


class AgentRunTests(unittest.TestCase):
    def test_run_returns_response_text(self):
        backend = MockBackend(responses="result text")
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        result = agent.run("hello")
        self.assertEqual(result, "result text")

    def test_run_initializes_backend(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        agent.run("hello")
        self.assertTrue(backend.initialized)

    def test_run_records_prompt_in_backend(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        agent.run("my prompt")
        self.assertEqual(backend.calls, ["my prompt"])

    def test_run_multiple_calls_reuse_backend(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        agent.run("first")
        agent.run("second")
        self.assertEqual(backend.calls, ["first", "second"])

    def test_run_multi_turn_responses(self):
        backend = MockBackend(responses=["first", "second"])
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        self.assertEqual(agent.run("q1"), "first")
        self.assertEqual(agent.run("q2"), "second")

    def test_run_accepts_force_new_conversation_kwarg(self):
        """Backward compat: force_new_conversation is accepted but ignored."""
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        result = agent.run("hello", force_new_conversation=True)
        self.assertEqual(result, "ok")


class AgentCloseTests(unittest.TestCase):
    def test_close_delegates_to_backend(self):
        backend = MockBackend()
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        agent.close()
        self.assertTrue(backend.closed)

    def test_context_manager_calls_close(self):
        backend = MockBackend(responses="done")
        with _StubAgent(
            settings=_make_settings(),
            backend=backend,
        ) as agent:
            result = agent.run("hello")
        self.assertEqual(result, "done")
        self.assertTrue(backend.closed)


class CircuitBreakerTests(unittest.TestCase):
    def test_circuit_breaker_blocks_after_threshold(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(circuit_breaker_threshold=3),
            backend=backend,
        )
        agent._consecutive_failures = 3
        with self.assertRaises(RuntimeError) as ctx:
            agent.run("hello")
        self.assertIn("Circuit breaker open", str(ctx.exception))

    def test_record_success_resets_counter(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        agent._consecutive_failures = 5
        agent._record_success()
        self.assertEqual(agent._consecutive_failures, 0)

    def test_record_failure_increments_counter(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        agent._record_failure()
        agent._record_failure()
        self.assertEqual(agent._consecutive_failures, 2)

    def test_backoff_delay_grows_with_attempt(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(rate_limit_base_delay_seconds=1.0),
            backend=backend,
        )
        delay = agent._backoff_delay(3)
        self.assertGreaterEqual(delay, 8.0)

    def test_parse_retry_after_extracts_seconds(self):
        exc = _HttpError("rate limited", 429, {"Retry-After": "30"})
        result = Agent._parse_retry_after(exc)
        self.assertEqual(result, 30.0)

    def test_parse_retry_after_returns_none_when_absent(self):
        exc = Exception("no response attr")
        result = Agent._parse_retry_after(exc)
        self.assertIsNone(result)

    def test_timeout_retries_once_then_raises(self):
        """Agent retries once on TimeoutError, then re-raises."""
        call_count = 0

        class TimeoutBackend(MockBackend):
            def call(self, prompt):
                nonlocal call_count
                call_count += 1
                raise TimeoutError("stream timeout")

        backend = TimeoutBackend()
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        with self.assertRaises(TimeoutError):
            agent.run("hello")
        # First attempt + one retry = 2 calls total
        self.assertEqual(call_count, 2)


# ── Async Tests ──────────────────────────────────────────────────────────


class AgentRunAsyncTests(unittest.TestCase):
    """Tests for run_async() — mirrors AgentRunTests."""

    def test_run_async_returns_response_text(self):
        backend = MockBackend(responses="async result")
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        result = asyncio.run(agent.run_async("hello"))
        self.assertEqual(result, "async result")

    def test_run_async_records_prompt_in_backend(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        asyncio.run(agent.run_async("my prompt"))
        self.assertEqual(backend.calls, ["my prompt"])

    def test_run_async_multi_turn_responses(self):
        backend = MockBackend(responses=["first", "second"])
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )

        async def _multi_turn():
            r1 = await agent.run_async("q1")
            r2 = await agent.run_async("q2")
            return r1, r2

        r1, r2 = asyncio.run(_multi_turn())
        self.assertEqual(r1, "first")
        self.assertEqual(r2, "second")

    def test_run_async_initializes_backend(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        asyncio.run(agent.run_async("hello"))
        self.assertTrue(backend.initialized)


class AgentAsyncContextManagerTests(unittest.TestCase):
    """Tests for async context manager (__aenter__/__aexit__)."""

    def test_async_context_manager_calls_close(self):
        backend = MockBackend(responses="done")

        async def _run():
            async with _StubAgent(
                settings=_make_settings(),
                backend=backend,
            ) as agent:
                return await agent.run_async("hello")

        result = asyncio.run(_run())
        self.assertEqual(result, "done")
        self.assertTrue(backend.closed)


class AgentAsyncCircuitBreakerTests(unittest.TestCase):
    """Test circuit breaker works with run_async."""

    def test_circuit_breaker_blocks_async(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(circuit_breaker_threshold=3),
            backend=backend,
        )
        agent._consecutive_failures = 3
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(agent.run_async("hello"))
        self.assertIn("Circuit breaker open", str(ctx.exception))

    def test_async_timeout_retries_once_then_raises(self):
        call_count = 0

        class AsyncTimeoutBackend(MockBackend):
            async def call_async(self, prompt):
                nonlocal call_count
                call_count += 1
                raise TimeoutError("stream timeout")

        backend = AsyncTimeoutBackend()
        agent = _StubAgent(
            settings=_make_settings(),
            backend=backend,
        )
        with self.assertRaises(TimeoutError):
            asyncio.run(agent.run_async("hello"))
        self.assertEqual(call_count, 2)


class AgentLoadSkillTests(unittest.TestCase):
    """Tests for the load_skill helper function."""

    def test_load_skill_raises_for_unknown_name(self):
        from Tableau2PowerBI.core.agent.base import load_skill

        with self.assertRaises(FileNotFoundError):
            load_skill("nonexistent_skill_xyz")


class AgentPromptSizeTests(unittest.TestCase):
    """Tests for the _log_prompt_size method."""

    def test_large_prompt_triggers_warning(self):
        backend = MockBackend(responses="ok")
        agent = _StubAgent(
            settings=_make_settings(prompt_warning_kb=0.001),
            backend=backend,
        )
        with self.assertLogs("Tableau2PowerBI", level="WARNING") as cm:
            agent.run("A" * 100)
        self.assertTrue(any("Large prompt" in m for m in cm.output))


class AgentRateLimitTests(unittest.TestCase):
    """Tests for HTTP 429 retry logic in run() and run_async()."""

    def test_run_retries_on_429_then_succeeds(self):
        """Sync run() retries after 429, succeeds on second attempt."""
        call_count = 0

        class RateLimitOnceBackend(MockBackend):
            def call(self, prompt):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise _HttpError("rate limited", 429, {"Retry-After": "0"})
                from Tableau2PowerBI.core.backends import LLMResponse

                return LLMResponse(text="recovered", tokens_in=1, tokens_out=1, elapsed_seconds=0.01)

        backend = RateLimitOnceBackend()
        agent = _StubAgent(
            settings=_make_settings(
                rate_limit_max_retries=2,
                rate_limit_base_delay_seconds=0.0,
            ),
            backend=backend,
        )
        result = agent.run("hello")
        self.assertEqual(result, "recovered")
        self.assertEqual(call_count, 2)

    def test_run_429_exhausts_retries_raises(self):
        """Sync run() raises after exhausting all 429 retries."""

        class AlwaysRateLimitBackend(MockBackend):
            def call(self, prompt):
                raise _HttpError("rate limited", 429, {"Retry-After": "0"})

        backend = AlwaysRateLimitBackend()
        agent = _StubAgent(
            settings=_make_settings(
                rate_limit_max_retries=1,
                rate_limit_base_delay_seconds=0.0,
            ),
            backend=backend,
        )
        with self.assertRaisesRegex(Exception, "rate limited"):
            agent.run("hello")

    def test_run_async_retries_on_429_then_succeeds(self):
        """Async run_async() retries after 429, succeeds on second attempt."""
        call_count = 0

        class AsyncRateLimitOnceBackend(MockBackend):
            async def call_async(self, prompt):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise _HttpError("rate limited", 429, {"Retry-After": "0"})
                from Tableau2PowerBI.core.backends import LLMResponse

                return LLMResponse(text="async-recovered", tokens_in=1, tokens_out=1, elapsed_seconds=0.01)

        backend = AsyncRateLimitOnceBackend()
        agent = _StubAgent(
            settings=_make_settings(
                rate_limit_max_retries=2,
                rate_limit_base_delay_seconds=0.0,
            ),
            backend=backend,
        )
        result = asyncio.run(agent.run_async("hello"))
        self.assertEqual(result, "async-recovered")
        self.assertEqual(call_count, 2)

    def test_run_async_429_exhausts_retries_raises(self):
        """Async run_async() raises after exhausting all 429 retries."""

        class AlwaysAsyncRateLimitBackend(MockBackend):
            async def call_async(self, prompt):
                raise _HttpError("rate limited", 429, {"Retry-After": "0"})

        backend = AlwaysAsyncRateLimitBackend()
        agent = _StubAgent(
            settings=_make_settings(
                rate_limit_max_retries=1,
                rate_limit_base_delay_seconds=0.0,
            ),
            backend=backend,
        )
        with self.assertRaisesRegex(Exception, "rate limited"):
            asyncio.run(agent.run_async("hello"))

    def test_run_non_429_error_raises_immediately(self):
        """Non-429 exceptions are not retried."""
        call_count = 0

        class ServerErrorBackend(MockBackend):
            def call(self, prompt):
                nonlocal call_count
                call_count += 1
                raise _HttpError("server error", 500)

        backend = ServerErrorBackend()
        agent = _StubAgent(
            settings=_make_settings(rate_limit_max_retries=3),
            backend=backend,
        )
        with self.assertRaisesRegex(Exception, "server error"):
            agent.run("hello")
        self.assertEqual(call_count, 1)


class AgentValidationRunnerTests(unittest.TestCase):
    """Tests for Agent.run_with_validation shared behavior."""

    def test_run_with_validation_returns_parsed_on_first_attempt(self):
        backend = MockBackend(responses='{"ok": true}')
        agent = _StubAgent(
            settings=_make_settings(max_validation_retries=2),
            backend=backend,
        )

        def parser(text: str) -> bool:
            return '"ok": true' in text

        result = agent.run_with_validation(
            "prompt",
            parser,
            label="validation-test",
        )

        self.assertTrue(result)
        self.assertEqual(len(backend.calls), 1)

    def test_run_with_validation_injects_feedback_on_retry(self):
        backend = MockBackend(responses=["bad payload", '{"ok": true}'])
        agent = _StubAgent(
            settings=_make_settings(max_validation_retries=2),
            backend=backend,
        )

        def parser(text: str) -> dict:
            if text == "bad payload":
                raise ValueError("schema mismatch")
            return {"ok": True}

        result = agent.run_with_validation(
            "base prompt",
            parser,
            label="validation-test",
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("Your previous response failed validation", backend.calls[1])
        self.assertIn("schema mismatch", backend.calls[1])

    def test_run_with_validation_uses_error_formatter(self):
        backend = MockBackend(responses=["first", "second"])
        agent = _StubAgent(
            settings=_make_settings(max_validation_retries=1),
            backend=backend,
        )

        def parser(text: str) -> str:
            if text == "first":
                raise ValueError("raw message")
            return text

        result = agent.run_with_validation(
            "prompt",
            parser,
            label="validation-test",
            error_formatter=lambda exc: f"FORMATTED:{exc}",
        )

        self.assertEqual(result, "second")
        self.assertIn("FORMATTED:raw message", backend.calls[1])

    def test_run_with_validation_raises_with_label_after_exhaustion(self):
        backend = MockBackend(responses=["bad", "still bad"])
        agent = _StubAgent(
            settings=_make_settings(max_validation_retries=1),
            backend=backend,
        )

        def parser(_text: str) -> str:
            raise ValueError("cannot parse")

        with self.assertRaises(ValueError) as ctx:
            agent.run_with_validation(
                "prompt",
                parser,
                label="critical-parse",
            )

        self.assertIn("critical-parse failed", str(ctx.exception))


class AgentValidationRunnerAsyncTests(unittest.TestCase):
    """Tests for Agent.run_with_validation_async shared behavior."""

    def test_run_with_validation_async_injects_feedback_on_retry(self):
        backend = MockBackend(responses=["bad", "good"])
        agent = _StubAgent(
            settings=_make_settings(max_validation_retries=2),
            backend=backend,
        )

        def parser(text: str) -> str:
            if text == "bad":
                raise ValueError("async-parse-error")
            return text

        async def _run() -> str:
            return await agent.run_with_validation_async(
                "base prompt",
                parser,
                label="async-validation-test",
            )

        result = asyncio.run(_run())
        self.assertEqual(result, "good")
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("async-parse-error", backend.calls[1])


# ── Context Length Exceeded Tests ────────────────────────────────────────


class ContextLengthExceededTests(unittest.TestCase):
    """Tests for context_length_exceeded detection in run() and run_async()."""

    def test_run_raises_context_length_exceeded_error(self):
        """run() wraps context_length_exceeded in ContextLengthExceededError."""

        class CtxBackend(MockBackend):
            def call(self, prompt):
                raise _ContextLengthError()

        agent = _StubAgent(
            settings=_make_settings(),
            backend=CtxBackend(),
        )
        with self.assertRaises(ContextLengthExceededError) as ctx:
            agent.run("big prompt")
        self.assertIn("KB", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, _ContextLengthError)
        self.assertGreater(ctx.exception.prompt_size_bytes, 0)

    def test_run_async_raises_context_length_exceeded_error(self):
        """run_async() wraps context_length_exceeded too."""

        class AsyncCtxBackend(MockBackend):
            async def call_async(self, prompt):
                raise _ContextLengthError()

        agent = _StubAgent(
            settings=_make_settings(),
            backend=AsyncCtxBackend(),
        )
        with self.assertRaises(ContextLengthExceededError) as ctx:
            asyncio.run(agent.run_async("big prompt"))
        self.assertIsInstance(ctx.exception.__cause__, _ContextLengthError)

    def test_run_other_400_not_caught(self):
        """A 400 error without context_length_exceeded code propagates as-is."""

        class BadRequestBackend(MockBackend):
            def call(self, prompt):
                raise _HttpError("invalid request", 400)

        agent = _StubAgent(
            settings=_make_settings(),
            backend=BadRequestBackend(),
        )
        with self.assertRaises(_HttpError):
            agent.run("hello")

    def test_context_length_error_does_not_increment_circuit_breaker(self):
        """ContextLengthExceededError does NOT trigger _record_failure."""

        class CtxBackend(MockBackend):
            def call(self, prompt):
                raise _ContextLengthError()

        agent = _StubAgent(
            settings=_make_settings(),
            backend=CtxBackend(),
        )
        self.assertEqual(agent._consecutive_failures, 0)
        with self.assertRaises(ContextLengthExceededError):
            agent.run("hello")
        # Failure counter must remain at 0
        self.assertEqual(agent._consecutive_failures, 0)

    def test_run_raises_context_length_via_body_dict(self):
        """run() detects context_length_exceeded from exc.body dict."""

        class BodyDictError(Exception):
            def __init__(self):
                super().__init__("error")
                self.status_code = 400
                self.body = {"code": "context_length_exceeded"}

        class BodyBackend(MockBackend):
            def call(self, prompt):
                raise BodyDictError()

        agent = _StubAgent(settings=_make_settings(), backend=BodyBackend())
        with self.assertRaises(ContextLengthExceededError):
            agent.run("big prompt")
