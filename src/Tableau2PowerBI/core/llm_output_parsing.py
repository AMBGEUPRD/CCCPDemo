"""LLM response parsing and JSON recovery utilities.

Provides helpers to extract, clean, and recover JSON from raw LLM output:

- :func:`extract_json_from_markdown` — parse JSON from fenced or plain text.
- :func:`strip_markdown_fences` — remove code fences without altering content.
- :func:`normalise_warnings` — coerce heterogeneous ``_warnings`` values into
  a uniform list of dicts.
- :func:`recover_malformed_json` — fix common escape and control-char issues.
"""

import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def extract_json_from_markdown(text: str) -> dict:
    """Extract a JSON object from markdown-fenced text or plain JSON.

    Handles two common LLM response formats:

    1. Fenced markdown: ````` ```json { ... } ``` `````
    2. Bare JSON: ``{ ... }``

    Raises:
        json.JSONDecodeError: If the text does not contain valid JSON.
    """
    text = text.strip()

    # Case 1: fenced markdown block
    match = re.search(r"```json\s*(\{.*\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    # Case 2: plain JSON
    return json.loads(text)


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from LLM responses.

    Handles ````` ```json ````` , ````` ```tmdl ````` , or bare ````` ``` `````
    wrappers that LLMs sometimes add despite being instructed not to.
    Safe to call when no fences are present.
    """
    stripped = re.sub(r"^```[a-zA-Z]*\s*", "", text.strip())
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def normalise_warnings(raw_warnings) -> list[dict]:
    """Coerce an LLM ``_warnings`` value into a uniform list of dicts.

    Handles: list of dicts, single dict, list of strings, or ``None``.
    Every entry in the returned list has keys ``severity``, ``code``,
    ``message``, and ``timestamp``.
    """
    if not isinstance(raw_warnings, list):
        raw_warnings = [raw_warnings] if raw_warnings else []

    normalised: list[dict] = []
    ts = datetime.now(timezone.utc).isoformat()
    for w in raw_warnings:
        if isinstance(w, dict):
            normalised.append(
                {
                    "severity": str(w.get("severity", "WARN")).upper(),
                    "code": w.get("code", "UNSTRUCTURED_WARNING"),
                    "message": w.get("message", str(w)),
                    "timestamp": ts,
                }
            )
        else:
            normalised.append(
                {
                    "severity": "WARN",
                    "code": "UNSTRUCTURED_WARNING",
                    "message": str(w),
                    "timestamp": ts,
                }
            )
    return normalised


# Valid single-character JSON escape letters (after a backslash).
_VALID_JSON_ESCAPES = frozenset('"\\bfnrt/')


def recover_malformed_json(text: str) -> dict | None:
    """Attempt to fix common LLM JSON malformations and return parsed dict.

    Handles two classes of problems inside JSON string values:

    1. **Literal control characters** (newlines, tabs, carriage returns)
       that should have been escaped.
    2. **Invalid escape sequences** like ``\\S``, ``\\T``, ``\\m`` —
       fixed by doubling the backslash.

    Returns the parsed dict on success, or ``None`` if recovery fails.
    """
    chars: list[str] = []
    in_string = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch == "\\" and in_string:
            if i + 1 < n:
                nxt = text[i + 1]
                if nxt == "u":
                    # \uXXXX — pass through 6 chars.
                    chars.append(text[i : i + 6])
                    i += 6
                    continue
                if nxt in _VALID_JSON_ESCAPES:
                    # Valid escape — pass through as-is.
                    chars.append(ch)
                    chars.append(nxt)
                    i += 2
                    continue
                # Invalid escape (e.g. \S, \T, \m) — double the backslash.
                chars.append("\\\\")
                chars.append(nxt)
                i += 2
                continue
            # Trailing lone backslash — double it.
            chars.append("\\\\")
            i += 1
            continue

        if ch == '"':
            in_string = not in_string
            chars.append(ch)
            i += 1
            continue

        if in_string and ch in ("\n", "\r", "\t"):
            chars.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
            i += 1
            continue

        chars.append(ch)
        i += 1

    fixed = "".join(chars)
    try:
        result = json.loads(fixed)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    return None
