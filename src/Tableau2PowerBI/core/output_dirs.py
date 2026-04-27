"""Path-safety validators and output directory helpers.

Provides:

- :func:`validate_name` and :func:`resolve_safe_path` guard against
  directory-traversal attacks when using user-supplied names in paths.
- :func:`get_output_dir`, :func:`reset_output_dir`, :func:`ensure_output_dir`
  manage convention-based output directories for pipeline stages.
- :func:`save_json_locally` writes a dict as pretty-printed JSON to disk.
"""

import json
import logging
import shutil
from pathlib import Path

from Tableau2PowerBI.core.config import AgentSettings, get_agent_settings

logger = logging.getLogger(__name__)

# Characters forbidden in Windows file/folder names.
INVALID_NAME_CHARS = frozenset('\\/:*?"<>|')


def validate_name(label: str, value: str) -> str:
    """Validate a user-supplied name for use in file paths.

    Strips whitespace and rejects names containing characters that are
    illegal in Windows filenames or could enable directory traversal.

    Args:
        label: Human-readable label for error messages (e.g. ``"Workbook name"``).
        value: The name to validate.

    Returns:
        The trimmed name.

    Raises:
        ValueError: If *value* is empty or contains forbidden characters.
    """
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{label} cannot be empty.")
    if any(char in INVALID_NAME_CHARS for char in candidate):
        raise ValueError(f"{label} contains invalid path characters: {value!r}")
    return candidate


def resolve_safe_path(base_path: Path, relative_path: str) -> Path:
    """Resolve *relative_path* under *base_path*, refusing traversal escapes."""
    output_path = (base_path / relative_path).resolve()
    base_resolved = base_path.resolve()
    if output_path != base_resolved and base_resolved not in output_path.parents:
        raise ValueError(f"Refusing to write outside output directory: {relative_path}")
    return output_path


def save_json_locally(data: dict, output_path: str) -> None:
    """Write *data* as pretty-printed JSON to *output_path*, creating directories as needed."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_output_dir(agent_name: str, run_name: str, settings: AgentSettings | None = None) -> Path:
    """Return the output directory for a given agent and run (workbook) name.

    Follows the convention ``<output_root>/<agent_name>/<run_name>/``.
    """
    runtime_settings = settings or get_agent_settings()
    return runtime_settings.output_root / agent_name / run_name


def reset_output_dir(output_dir: Path) -> None:
    """Delete *output_dir* if it exists and recreate it empty.

    Ensures every pipeline run starts with a clean output directory so
    stale files from previous runs never survive.
    """
    if output_dir.exists():
        shutil.rmtree(output_dir)
        logger.info("Cleaned stale output directory: %s", output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def ensure_output_dir(output_dir: Path) -> None:
    """Create *output_dir* if it does not exist — without deleting contents.

    Used when reusing cached stage outputs during incremental runs.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
