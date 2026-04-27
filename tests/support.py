"""Shared test utilities.

Provides :func:`managed_tempdir`, a context manager that creates a
temporary directory under ``.test_tmp/`` and cleans it up on exit.
Used by all test modules to avoid polluting the project output directory.
"""

from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

# All test temp dirs live under this root, away from production output.
# Anchored to the project root (two levels up from this file) so the path
# is correct regardless of which directory pytest is invoked from.
TMP_ROOT = Path(__file__).parent.parent / ".test_tmp"


@contextmanager
def managed_tempdir():
    """Context manager that creates a unique temp directory and cleans up on exit."""
    TMP_ROOT.mkdir(exist_ok=True)
    tempdir = TMP_ROOT / f"tmp_{uuid.uuid4().hex}"
    tempdir.mkdir(parents=True, exist_ok=True)
    try:
        yield tempdir
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)
