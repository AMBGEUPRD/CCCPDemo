"""Shared fixtures and markers for evaluation tests.

Provides:

- ``@pytest.mark.eval`` — marker to select evaluation tests
- ``golden_dir`` — path to golden inputs for a given workbook
- ``eval_output_dir`` — temporary output dir for eval runs
- Pre-captured input JSON fixtures per agent
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_ROOT = PROJECT_ROOT / "data" / "golden"
SAMPLE_WORKBOOKS_DIR = PROJECT_ROOT / "data" / "input"
EVAL_TMP_ROOT = PROJECT_ROOT / ".eval_tmp"


# ── Markers ────────────────────────────────────────────────────────────────


def pytest_configure(config):
    """Register custom markers so pytest doesn't warn about unknown markers."""
    config.addinivalue_line("markers", "eval: mark test as a live-agent evaluation test")
    config.addinivalue_line("markers", "eval_capture: mark test as a golden-input capture step")


# ── Fixtures ───────────────────────────────────────────────────────────────


# The sample workbooks we evaluate against.  Each must have a matching
# directory under data/golden/<stem>/ with pre-captured stage-1 outputs.
_EVAL_WORKBOOKS = [
    "Netfix Workbook",
    "Supermercato",
    "VG Contest_Super Sample Superstore_Ryan Sleeper",
]


@pytest.fixture(params=_EVAL_WORKBOOKS, ids=_EVAL_WORKBOOKS)
def workbook_name(request) -> str:
    """Parametrised fixture yielding each golden workbook name."""
    return request.param


@pytest.fixture
def golden_dir(workbook_name: str) -> Path:
    """Return the golden-input directory for a given workbook.

    Skips the test if the golden directory doesn't exist yet
    (run ``capture_golden_inputs`` first).
    """
    path = GOLDEN_ROOT / workbook_name
    if not path.exists():
        pytest.skip(
            f"Golden inputs not found for '{workbook_name}'. " f"Run: python -m tests.evals.capture_golden_inputs"
        )
    return path


@pytest.fixture
def semantic_model_input(golden_dir: Path) -> dict:
    """Load the pre-captured semantic model input JSON."""
    path = golden_dir / "semantic_model_input.json"
    if not path.exists():
        pytest.skip(f"semantic_model_input.json not found in {golden_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def semantic_model_input_raw(golden_dir: Path) -> str:
    """Load the pre-captured semantic model input as raw JSON string."""
    path = golden_dir / "semantic_model_input.json"
    if not path.exists():
        pytest.skip(f"semantic_model_input.json not found in {golden_dir}")
    return path.read_text(encoding="utf-8")


@pytest.fixture
def report_input(golden_dir: Path) -> dict:
    """Load the pre-captured report input JSON."""
    path = golden_dir / "report_input.json"
    if not path.exists():
        pytest.skip(f"report_input.json not found in {golden_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def report_input_raw(golden_dir: Path) -> str:
    """Load the pre-captured report input as raw JSON string."""
    path = golden_dir / "report_input.json"
    if not path.exists():
        pytest.skip(f"report_input.json not found in {golden_dir}")
    return path.read_text(encoding="utf-8")


@pytest.fixture
def eval_output_dir(tmp_path: Path) -> Path:
    """Provide a unique temporary output directory for an eval run."""
    out = tmp_path / f"eval_{uuid.uuid4().hex[:8]}"
    out.mkdir(parents=True, exist_ok=True)
    return out
