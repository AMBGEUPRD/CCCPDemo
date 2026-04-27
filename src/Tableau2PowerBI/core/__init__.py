"""Core framework for the Tableau → Power BI migration pipeline.

Module map
----------

Agent base classes  (``agent/``)
    base.py            :class:`Agent` — LLM calling, retries, prompt loading,
                       backend orchestration.
    deterministic.py   :class:`DeterministicAgent` — same interface, but model
                       invocation is disabled (metadata extractor, skeleton,
                       assembler).
    semaphores.py      Process-wide LLM concurrency limits (sync + async).
    validation.py      Validation-with-retry loop shared by all LLM agents.

LLM backends  (``backends/``)
    model_backend.py       Abstract :class:`ModelBackend` interface.
    responses_backend.py   Azure OpenAI Responses API (GPT, o-series).
    chat_completions.py    Chat Completions API (Anthropic, generic).
    mock.py                In-memory mock for unit testing.
    factory.py             :func:`create_backend` — picks the right backend
                           from a model deployment name.
    shared_clients.py      Per-endpoint client caching.

Run history and stage cache  (``run_history/``)
    run_history.py     :class:`RunHistory` — CRUD for run manifests on disk.
    run_manifest.py    :class:`RunManifest` dataclass.
    stage_record.py    :class:`StageRecord` — one stage's status + metrics.
    stage_status.py    :class:`StageStatus` enum (not_started, completed, …).
    stage_cache.py     ``STAGE_GRAPH`` (authoritative DAG of pipeline stages),
                       :class:`StageInfo`, :class:`SkipDecision`, input hashing,
                       skip logic, and ``resolve_stages_to_run()``.

Configuration and constants
    config.py          :class:`AgentSettings` dataclass — endpoints, models,
                       timeouts.  All secrets from env vars.  Also contains
                       PBIP JSON schema URLs and TMDL TAB constant.

Shared domain models
    models.py          :class:`MigrationWarning` — used across all agents.

Prompt and response helpers
    prompt_utils.py    Token-efficient serialisation for prompt assembly
                       (``compact_json``).
    json_response.py   Shared JSON parsing/recovery for LLM responses.

Observability
    token_tracker.py   Pipeline-wide token usage accumulator.

Filesystem utilities
    utils.py           Logging setup, path safety, JSON helpers, output-dir
                       management.
"""

from Tableau2PowerBI.core.agent import Agent, DeterministicAgent
from Tableau2PowerBI.core.backends import (
    LLMResponse,
    MockBackend,
    ModelBackend,
    ResponsesBackend,
    create_backend,
)
from Tableau2PowerBI.core.config import (
    SCHEMA_EDITOR,
    SCHEMA_LOCAL,
    SCHEMA_PBIR,
    SCHEMA_PBISM,
    SCHEMA_PLATFORM,
    TAB,
    AgentSettings,
    get_agent_settings,
)
from Tableau2PowerBI.core.logging_setup import setup_logging
from Tableau2PowerBI.core.llm_output_parsing import extract_json_from_markdown
from Tableau2PowerBI.core.output_dirs import (
    INVALID_NAME_CHARS,
    ensure_output_dir,
    get_output_dir,
    reset_output_dir,
    resolve_safe_path,
    save_json_locally,
    validate_name,
)

__all__ = [
    "Agent",
    "AgentSettings",
    "DeterministicAgent",
    "LLMResponse",
    "MockBackend",
    "ModelBackend",
    "ResponsesBackend",
    "create_backend",
    "get_agent_settings",
    "INVALID_NAME_CHARS",
    "SCHEMA_EDITOR",
    "SCHEMA_LOCAL",
    "SCHEMA_PBIR",
    "SCHEMA_PBISM",
    "SCHEMA_PLATFORM",
    "TAB",
    "ensure_output_dir",
    "extract_json_from_markdown",
    "get_output_dir",
    "reset_output_dir",
    "resolve_safe_path",
    "save_json_locally",
    "setup_logging",
    "validate_name",
]
