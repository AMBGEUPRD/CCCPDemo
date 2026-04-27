"""LLMResponse — uniform response object returned by all LLM backends."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Uniform response object returned by all backends.

    Attributes:
        text: The full accumulated response text from the LLM.
        tokens_in: Number of input (prompt) tokens consumed.
        tokens_out: Number of output (completion) tokens generated.
        elapsed_seconds: Wall-clock time for the call in seconds.
    """

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    elapsed_seconds: float = 0.0
