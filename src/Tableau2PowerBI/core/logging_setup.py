"""Logging configuration for the Tableau2PowerBI pipeline.

Provides :func:`setup_logging` to configure the package logger with
Uvicorn-style ANSI-coloured output and :func:`shorten_abs_paths` to
keep log lines readable on Windows.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Matches Windows absolute paths like C:\Users\foo\bar\baz.
_ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\\/](?:[^\s\\\/]+[\\\/]){2,}[^\s\\\/]*")


def shorten_abs_paths(text: str, keep_parts: int = 3) -> str:
    """Replace Windows absolute paths with just the last *keep_parts* components.

    Example::

        >>> shorten_abs_paths("Saved: C:\\\\Users\\\\me\\\\project\\\\data\\\\out\\\\file.tmdl")
        'Saved: data/out/file.tmdl'
    """

    def _replace(m: re.Match) -> str:
        parts = m.group(0).replace("\\", "/").split("/")
        return "/".join(parts[-keep_parts:]) if len(parts) > keep_parts else m.group(0)

    return _ABS_PATH_RE.sub(_replace, text)


class _ColorFormatter(logging.Formatter):
    """Uvicorn-aligned coloured formatter: ``LEVEL:     message``."""

    _COLORS = {
        "DEBUG": "\033[1m",  # bold
        "INFO": "\033[32m",  # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",  # red
        "CRITICAL": "\033[1;31m",  # bold red
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        levelname = record.levelname
        # Pad so the message column always starts at the same position,
        # exactly matching Uvicorn's default output alignment.
        padding = " " * max(8 - len(levelname), 0)
        color = self._COLORS.get(levelname, "")
        reset = self._RESET if color else ""
        record.levelprefix = f"{color}{levelname}:{reset}{padding}"
        formatted = super().format(record)
        return shorten_abs_paths(formatted)


# Loggers whose INFO-level chatter clutters pipeline output.
_NOISY_LOGGERS = (
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.identity",
    "azure.ai",
    "httpx",
    "openai",
    "watchfiles",
)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the ``Tableau2PowerBI`` logger hierarchy.

    Produces output in Uvicorn's ``LEVEL:     message`` style with
    ANSI colour highlighting (green INFO, yellow WARNING, red ERROR).

    Call this **once** from each entry point.  Library code must never call it.

    Args:
        level: Logging level (default ``INFO``).
    """
    pkg_logger = logging.getLogger("Tableau2PowerBI")

    # Guard against duplicate handlers when called more than once.
    if pkg_logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(_ColorFormatter("%(levelprefix)s %(message)s"))

    pkg_logger.setLevel(level)
    pkg_logger.addHandler(handler)
    pkg_logger.propagate = False

    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)
