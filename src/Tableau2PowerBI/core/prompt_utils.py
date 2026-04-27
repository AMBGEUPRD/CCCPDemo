"""Prompt construction utilities — token-efficient serialisation helpers.

All functions in this module are used during **prompt assembly** to
reduce input token consumption.  They do NOT affect disk output
(which continues to use ``indent=2`` for human readability).
"""

from __future__ import annotations

import json
from typing import Any


def compact_json(obj: Any, *, ensure_ascii: bool = False) -> str:
    """Serialise *obj* as compact JSON (no whitespace padding).

    Uses ``separators=(',', ':')`` to eliminate the indent-level
    whitespace and trailing spaces that ``indent=2`` / default
    ``json.dumps`` would inject.  On typical Tableau metadata payloads
    this saves ~25-30 % of the prompt token count.

    Args:
        obj: Any JSON-serialisable Python object.
        ensure_ascii: Passed through to ``json.dumps``.  Defaults to
            ``False`` so non-ASCII characters (accented table names,
            locale strings, …) are preserved verbatim.

    Returns:
        A compact single-line JSON string.
    """
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=ensure_ascii)
