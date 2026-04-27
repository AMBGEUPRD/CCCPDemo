"""Response parsing and content normalization helpers for PBIR report generation."""

from __future__ import annotations

import json
import logging

from Tableau2PowerBI.core.llm_output_parsing import (
    normalise_warnings,
    recover_malformed_json,
    strip_markdown_fences,
)


def recover_truncated_json(text: str) -> dict | None:
    """Attempt to recover a truncated JSON object by closing open structures."""
    text = text.rstrip()

    if text.endswith("}"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    last_comma = text.rfind(',"')
    if last_comma > 0:
        candidate = text[:last_comma] + "}"
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    for i in range(len(text) - 1, max(0, len(text) - 5000), -1):
        if text[i] == '"' and (i + 1 >= len(text) or text[i + 1] in (",", "}")):
            candidate = text[: i + 1] + "}"
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    warnings_start = text.rfind('"_warnings"')
    if warnings_start > 0:
        last_comma_before = text.rfind(",", 0, warnings_start)
        if last_comma_before > 0:
            candidate = text[:last_comma_before] + "}"
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    return None


def normalise_content(content: object) -> str:
    """Coerce any value into a plain UTF-8 string for writing to disk."""
    if isinstance(content, (dict, list)):
        return json.dumps(content, indent=2, ensure_ascii=False)
    if not isinstance(content, str):
        return str(content)

    try:
        obj = json.loads(content)
        if isinstance(obj, (dict, list)):
            return json.dumps(obj, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        recovered = recover_malformed_json(content)
        if recovered is not None:
            return json.dumps(recovered, indent=2, ensure_ascii=False)

        recovered = recover_truncated_json(content)
        if recovered is not None:
            logging.getLogger(__name__).warning("File content recovered from truncation (%d chars)", len(content))
            return json.dumps(recovered, indent=2, ensure_ascii=False)

    return content


def parse_response(
    response: str,
    non_file_keys: set[str],
) -> tuple[dict[str, str], list]:
    """Parse, normalise, and validate a raw LLM response envelope."""
    clean = strip_markdown_fences(response)

    raw = None
    parse_errors: list[str] = []

    try:
        raw = json.loads(clean)
    except json.JSONDecodeError as exc:
        parse_errors.append(f"Direct parse: {exc}")
        if "Extra data" in exc.msg and exc.pos > 0:
            try:
                raw = json.loads(clean[: exc.pos])
                logging.getLogger(__name__).warning(
                    "JSON recovered by dropping trailing data at pos %d (%d chars removed)",
                    exc.pos,
                    len(clean) - exc.pos,
                )
            except json.JSONDecodeError:
                pass

    if raw is None:
        recovered = recover_malformed_json(clean)
        if recovered is not None:
            raw = recovered
            logging.getLogger(__name__).warning(
                "JSON recovered after escaping control chars (%d chars)",
                len(clean),
            )
        else:
            parse_errors.append("recover_malformed_json returned None")

    if raw is None:
        recovered = recover_truncated_json(clean)
        if recovered is not None:
            raw = recovered
            logging.getLogger(__name__).warning(
                "JSON recovered from truncation - some files may be missing. Recovered %d keys from %d chars.",
                len(recovered),
                len(clean),
            )
        else:
            parse_errors.append("Truncation recovery failed")

    if raw is None:
        raise ValueError(
            f"Response is not valid JSON after all recovery attempts. "
            f"Errors: {'; '.join(parse_errors)}. "
            f"First 300 chars: {clean[:300]!r}"
        )

    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object, got {type(raw).__name__}")

    files: dict[str, str] = {}
    for key, content in raw.items():
        if key in non_file_keys:
            continue
        files[key] = normalise_content(content)

    warnings = normalise_warnings(raw.get("_warnings", []))
    return files, warnings
