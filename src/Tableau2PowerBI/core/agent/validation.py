"""Shared validation/retry helpers for Agent response parsing."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, TypeVar

TParsed = TypeVar("TParsed")


def default_validation_feedback(error_text: str) -> str:
    """Build retry feedback text injected after a validation failure."""
    return (
        "Your previous response failed validation with these errors:\n"
        f"{error_text}\n\n"
        "Fix the issues and return corrected JSON only."
    )


def run_with_validation(
    prompt: str,
    parser: Callable[[str], TParsed],
    *,
    label: str,
    max_retries: int,
    run_call: Callable[[str, bool], str],
    logger: logging.Logger,
    parse_exceptions: tuple[type[Exception], ...] = (ValueError,),
    error_formatter: Callable[[Exception], str] | None = None,
    feedback_builder: Callable[[str], str] = default_validation_feedback,
) -> TParsed:
    """Run a prompt with parser validation and bounded retry-with-feedback."""
    last_error: str | None = None

    for attempt in range(max_retries + 1):
        current_prompt = prompt
        if last_error is not None:
            current_prompt = f"{prompt}\n\n---\n" f"{feedback_builder(last_error)}"

        response = run_call(current_prompt, attempt == 0)

        try:
            return parser(response)
        except parse_exceptions as exc:
            last_error = error_formatter(exc) if error_formatter else str(exc)
            logger.warning(
                "%s attempt %d/%d failed: %s",
                label,
                attempt + 1,
                max_retries + 1,
                last_error[:300],
            )

    raise ValueError(f"{label} failed after {max_retries + 1} attempts. " f"Last error: {last_error}")


async def run_with_validation_async(
    prompt: str,
    parser: Callable[[str], TParsed],
    *,
    label: str,
    max_retries: int,
    run_call: Callable[[str, bool], Awaitable[str]],
    logger: logging.Logger,
    parse_exceptions: tuple[type[Exception], ...] = (ValueError,),
    error_formatter: Callable[[Exception], str] | None = None,
    feedback_builder: Callable[[str], str] = default_validation_feedback,
) -> TParsed:
    """Async variant of run_with_validation."""
    last_error: str | None = None

    for attempt in range(max_retries + 1):
        current_prompt = prompt
        if last_error is not None:
            current_prompt = f"{prompt}\n\n---\n" f"{feedback_builder(last_error)}"

        response = await run_call(current_prompt, attempt == 0)

        try:
            return parser(response)
        except parse_exceptions as exc:
            last_error = error_formatter(exc) if error_formatter else str(exc)
            logger.warning(
                "%s attempt %d/%d failed: %s",
                label,
                attempt + 1,
                max_retries + 1,
                last_error[:300],
            )

    raise ValueError(f"{label} failed after {max_retries + 1} attempts. " f"Last error: {last_error}")
