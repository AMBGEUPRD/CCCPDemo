"""Tests for the shared validation/retry helpers in core.agent.validation."""

from __future__ import annotations

import asyncio
import logging
import unittest

from Tableau2PowerBI.core.agent.validation import (
    default_validation_feedback,
    run_with_validation,
    run_with_validation_async,
)


class DefaultValidationFeedbackTests(unittest.TestCase):
    """Tests for the feedback text builder."""

    def test_includes_error_text(self):
        result = default_validation_feedback("missing field 'name'")
        self.assertIn("missing field 'name'", result)

    def test_includes_instruction_to_fix(self):
        result = default_validation_feedback("bad schema")
        self.assertIn("Fix the issues", result)

    def test_empty_error_text(self):
        result = default_validation_feedback("")
        self.assertIn("Fix the issues", result)


# ── run_with_validation (sync) ───────────────────────────────────────


class RunWithValidationTests(unittest.TestCase):
    """Tests for the synchronous retry-with-feedback loop."""

    def _logger(self) -> logging.Logger:
        return logging.getLogger("test.validation")

    def test_returns_parsed_on_first_success(self):
        calls: list[str] = []

        def run_call(prompt: str, is_first: bool) -> str:
            calls.append(prompt)
            return "ok"

        result = run_with_validation(
            "prompt",
            parser=lambda r: r.upper(),
            label="Test",
            max_retries=2,
            run_call=run_call,
            logger=self._logger(),
        )
        self.assertEqual(result, "OK")
        self.assertEqual(len(calls), 1)

    def test_retries_on_parser_failure_then_succeeds(self):
        attempt_counter = {"n": 0}

        def run_call(prompt: str, is_first: bool) -> str:
            attempt_counter["n"] += 1
            return f"response-{attempt_counter['n']}"

        def parser(response: str) -> str:
            if response == "response-1":
                raise ValueError("bad response")
            return response

        result = run_with_validation(
            "prompt",
            parser=parser,
            label="Test",
            max_retries=2,
            run_call=run_call,
            logger=self._logger(),
        )
        self.assertEqual(result, "response-2")
        self.assertEqual(attempt_counter["n"], 2)

    def test_raises_after_exhausting_retries(self):
        def run_call(prompt: str, is_first: bool) -> str:
            return "bad"

        def parser(response: str) -> str:
            raise ValueError("always fails")

        with self.assertRaises(ValueError) as ctx:
            run_with_validation(
                "prompt",
                parser=parser,
                label="MyAgent",
                max_retries=1,
                run_call=run_call,
                logger=self._logger(),
            )
        self.assertIn("MyAgent", str(ctx.exception))
        self.assertIn("2 attempts", str(ctx.exception))

    def test_feedback_injected_on_retry(self):
        calls: list[str] = []
        attempt_counter = {"n": 0}

        def run_call(prompt: str, is_first: bool) -> str:
            calls.append(prompt)
            attempt_counter["n"] += 1
            return f"resp-{attempt_counter['n']}"

        def parser(response: str) -> str:
            if response == "resp-1":
                raise ValueError("missing key 'x'")
            return response

        run_with_validation(
            "original prompt",
            parser=parser,
            label="Test",
            max_retries=2,
            run_call=run_call,
            logger=self._logger(),
        )
        # First call has the original prompt only
        self.assertNotIn("validation", calls[0])
        # Second call has feedback appended
        self.assertIn("missing key 'x'", calls[1])

    def test_custom_error_formatter(self):
        attempt_counter = {"n": 0}

        def run_call(prompt: str, is_first: bool) -> str:
            attempt_counter["n"] += 1
            return f"r{attempt_counter['n']}"

        def parser(response: str) -> str:
            if response == "r1":
                raise ValueError("raw error")
            return response

        def formatter(exc: Exception) -> str:
            return f"FORMATTED: {exc}"

        calls: list[str] = []
        original_run_call = run_call

        def tracking_run_call(prompt: str, is_first: bool) -> str:
            calls.append(prompt)
            return original_run_call(prompt, is_first)

        run_with_validation(
            "p",
            parser=parser,
            label="Test",
            max_retries=2,
            run_call=tracking_run_call,
            logger=self._logger(),
            error_formatter=formatter,
        )
        self.assertIn("FORMATTED: raw error", calls[1])

    def test_custom_feedback_builder(self):
        attempt_counter = {"n": 0}

        def run_call(prompt: str, is_first: bool) -> str:
            attempt_counter["n"] += 1
            return f"r{attempt_counter['n']}"

        def parser(response: str) -> str:
            if response == "r1":
                raise ValueError("err")
            return response

        calls: list[str] = []

        def tracking(prompt: str, is_first: bool) -> str:
            calls.append(prompt)
            return run_call(prompt, is_first)

        run_with_validation(
            "p",
            parser=parser,
            label="Test",
            max_retries=2,
            run_call=tracking,
            logger=self._logger(),
            feedback_builder=lambda e: f"CUSTOM FEEDBACK: {e}",
        )
        self.assertIn("CUSTOM FEEDBACK: err", calls[1])

    def test_custom_parse_exceptions(self):
        """Only the specified exception types trigger retries."""

        def run_call(prompt: str, is_first: bool) -> str:
            return "x"

        def parser(response: str) -> str:
            raise TypeError("wrong type")

        # TypeError is not in parse_exceptions by default → should propagate
        with self.assertRaises(TypeError):
            run_with_validation(
                "p",
                parser=parser,
                label="Test",
                max_retries=2,
                run_call=run_call,
                logger=self._logger(),
                parse_exceptions=(ValueError,),
            )

    def test_is_first_flag_true_only_on_first_attempt(self):
        flags: list[bool] = []
        attempt_counter = {"n": 0}

        def run_call(prompt: str, is_first: bool) -> str:
            flags.append(is_first)
            attempt_counter["n"] += 1
            return f"r{attempt_counter['n']}"

        def parser(response: str) -> str:
            if response == "r1":
                raise ValueError("retry")
            return response

        run_with_validation(
            "p",
            parser=parser,
            label="Test",
            max_retries=2,
            run_call=run_call,
            logger=self._logger(),
        )
        self.assertEqual(flags, [True, False])


# ── run_with_validation_async ────────────────────────────────────────


class RunWithValidationAsyncTests(unittest.TestCase):
    """Tests for the async retry-with-feedback loop."""

    def _logger(self) -> logging.Logger:
        return logging.getLogger("test.validation.async")

    def test_returns_parsed_on_first_success(self):
        async def run_call(prompt: str, is_first: bool) -> str:
            return "ok"

        result = asyncio.run(
            run_with_validation_async(
                "prompt",
                parser=lambda r: r.upper(),
                label="Test",
                max_retries=0,
                run_call=run_call,
                logger=self._logger(),
            )
        )
        self.assertEqual(result, "OK")

    def test_retries_on_failure_then_succeeds(self):
        counter = {"n": 0}

        async def run_call(prompt: str, is_first: bool) -> str:
            counter["n"] += 1
            return f"r{counter['n']}"

        def parser(response: str) -> str:
            if response == "r1":
                raise ValueError("bad")
            return response

        result = asyncio.run(
            run_with_validation_async(
                "p",
                parser=parser,
                label="Test",
                max_retries=2,
                run_call=run_call,
                logger=self._logger(),
            )
        )
        self.assertEqual(result, "r2")

    def test_raises_after_exhausting_retries(self):
        async def run_call(prompt: str, is_first: bool) -> str:
            return "bad"

        with self.assertRaises(ValueError) as ctx:
            asyncio.run(
                run_with_validation_async(
                    "p",
                    parser=lambda r: (_ for _ in ()).throw(ValueError("fail")),
                    label="Async",
                    max_retries=1,
                    run_call=run_call,
                    logger=self._logger(),
                )
            )
        self.assertIn("Async", str(ctx.exception))
