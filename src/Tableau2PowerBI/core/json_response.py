"""Shared helpers for parsing JSON emitted by LLM responses."""

from __future__ import annotations

import json
import logging
from typing import Any

from Tableau2PowerBI.core.llm_output_parsing import recover_malformed_json, strip_markdown_fences


def parse_llm_json_object(
    response: str,
    *,
    logger: logging.Logger | None = None,
    enable_recovery: bool = True,
) -> dict[str, Any]:
    """Parse a model response into a JSON object.

    Steps:
    1. Strip markdown fences.
    2. Try direct JSON parse.
    3. Optionally attempt malformed-escape recovery.

    Raises:
        ValueError: If parsing fails or the payload is not a JSON object.
    """
    clean = strip_markdown_fences(response)

    try:
        raw = json.loads(clean)
    except json.JSONDecodeError as exc:
        if not enable_recovery:
            raise ValueError(f"Response is not valid JSON. First 300 chars: {clean[:300]!r}") from exc

        recovered = recover_malformed_json(clean)
        if recovered is None:
            raise ValueError(
                "Response is not valid JSON and recovery failed. " f"First 300 chars: {clean[:300]!r}"
            ) from exc

        if logger is not None:
            logger.warning("JSON recovered after malformed escape fix")
        raw = recovered

    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object, got {type(raw).__name__}")

    return raw
