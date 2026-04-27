"""Centralised configuration and shared constants for the agent pipeline.

Configuration
~~~~~~~~~~~~~
All runtime-sensitive values (endpoints, keys) are read from environment
variables so that secrets never appear in source control.

Local development:
    Set ``PROJECT_ENDPOINT`` (and optionally ``PROJECT_API_KEY``) in a
    ``.env`` file or your shell profile.

Azure:
    Provide the same variables via App Service → Configuration or
    Key Vault references.  ``DefaultAzureCredential`` handles auth
    so ``PROJECT_API_KEY`` is typically unused.

Per-agent model overrides:
    Each LLM agent can use a different model.  Set the corresponding
    environment variable (e.g. ``MODEL_DAX_MEASURES=claude-opus-4.6``)
    or pass values programmatically via ``AgentSettings``.

Constants
~~~~~~~~~
PBIP JSON schema URLs and TMDL formatting constants that must match
what Power BI Desktop expects.  Previously in ``constants.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Default endpoint used when PROJECT_ENDPOINT env var is not set.
# This points to the Azure AI Foundry project that hosts the pipeline agents.
_DEFAULT_ENDPOINT = "https://bimigrator-resource.services.ai.azure.com" "/api/projects/bimigrator"

# Maps model deployment names to the backend type they require.
# "responses" → OpenAI Responses API (GPT, o-series)
_DEFAULT_MODEL_BACKENDS: dict[str, str] = {
    "gpt-4.1": "responses",
    "gpt-4.1-mini": "responses",
    "gpt-4.1-nano": "responses",
    "gpt-5.4": "responses",
    "o3": "responses",
    "o4-mini": "responses",
}

# Maps per-agent config field names to their environment variable names.
# The skill_name (e.g. "tmdl_measures_generator_agent") is looked up here
# to find the right config attribute.
# NOTE: Only LLM-powered agents appear here.  Deterministic agents
# (tableau_metadata_extractor_agent, pbip_project_skeleton_agent,
# pbip_project_assembler_agent) don't call a model and therefore
# have no per-agent model override.
_SKILL_TO_MODEL_FIELD: dict[str, str] = {
    "pbip_semantic_model_generator_agent": "model_semantic_model",
    "tmdl_measures_generator_agent": "model_dax_measures",
    "pbir_report_generator_agent": "model_report_visuals",
    "target_technical_doc_agent": "model_target_technical_doc",
    "report_skeleton_agent": "model_report_skeleton",
    "report_page_visuals_agent": "model_report_page_visuals",
    "tableau_functional_doc_agent": "model_functional_doc",
    "warnings_reviewer_agent": "model_warnings_reviewer",
}


@dataclass(frozen=True)
class AgentSettings:
    """Immutable configuration for all pipeline agents.

    Attributes:
        project_endpoint: Azure AI Foundry project URL.
        default_model: Fallback model for agents without an explicit override.
        openai_api_version: Azure OpenAI API version string.
        request_timeout_seconds: Timeout for the initial HTTP request.
        stream_timeout_seconds: Timeout for the streaming response body.
        prompt_warning_kb: Log a warning when the prompt exceeds this size.
        functional_doc_input_threshold_kb: Use slim FDD input above this size.
        output_root: Base directory for all agent output artefacts.
        max_validation_retries: Number of LLM validation retries before giving up.
        model_semantic_model: Model for the semantic model generator agent.
        model_dax_measures: Model for the DAX measures generator agent.
        model_report_visuals: Model for the PBIR report generator agent.
        model_target_technical_doc: Model for the target technical doc agent.
        model_report_skeleton: Model for the report skeleton agent.
        model_report_page_visuals: Model for the report page visuals agent.
        model_functional_doc: Model for the functional doc agent.
        model_warnings_reviewer: Model for the warnings reviewer agent.
        model_backends: Maps model deployment names → backend types.
        tdd_max_prompt_tokens: Token budget for TDD prompts before chunking is triggered.
    """

    project_endpoint: str
    tenant_id: str = ""
    default_model: str = "gpt-4.1"
    openai_api_version: str = "2025-01-01-preview"
    request_timeout_seconds: int = 300
    stream_timeout_seconds: int = 300
    prompt_warning_kb: int = 80
    functional_doc_input_threshold_kb: int = 100
    output_root: Path = Path("data/output")
    runs_root: Path = Path("data/runs")
    max_runs_per_workbook: int = 10
    max_validation_retries: int = 2
    rate_limit_max_retries: int = 4
    rate_limit_base_delay_seconds: float = 1.0
    circuit_breaker_threshold: int = 3
    page_generation_workers: int = 2
    page_launch_stagger_seconds: float = 0.5
    max_concurrent_llm_calls: int = 4

    # ── Per-agent model overrides ────────────────────────────────────────
    # Tier A — highest complexity, frontier models for quality
    model_semantic_model: str = "gpt-5.4"
    model_dax_measures: str = "gpt-5.4"
    model_report_visuals: str = "gpt-5.4"
    model_target_technical_doc: str = "gpt-5.4"
    # Tier B/C — moderate/low complexity, faster models for speed
    model_report_skeleton: str = "gpt-4.1-mini"
    model_report_page_visuals: str = "gpt-4.1-mini"
    model_functional_doc: str = "gpt-4.1-mini"
    model_warnings_reviewer: str = "gpt-4.1-mini"

    # ── TDD chunking ──────────────────────────────────────────────────────
    tdd_max_prompt_tokens: int = 100_000
    """Token budget for TDD prompts before the chunked-batch strategy is
    triggered.  Conservative default (100 K) suits gpt-5.4's 1 M-token
    context while leaving ample headroom for the structured JSON response.
    Override via ``TDD_MAX_PROMPT_TOKENS`` environment variable."""

    # ── Model → backend mapping ─────────────────────────────────────────
    model_backends: dict[str, str] = field(
        default_factory=lambda: dict(_DEFAULT_MODEL_BACKENDS),
    )

    # ── helpers ──────────────────────────────────────────────────────────

    def get_model_for_agent(self, skill_name: str) -> str:
        """Resolve the model for a given agent by skill_name.

        Priority (highest → lowest):
        1. Environment variable (e.g. ``MODEL_DAX_MEASURES``)
        2. Per-agent field on this ``AgentSettings`` instance
        3. ``default_model``
        """
        field_name = _SKILL_TO_MODEL_FIELD.get(skill_name)
        if field_name is None:
            # Unknown agent — fall back to default_model
            return self.default_model

        # Check env var override: MODEL_DAX_MEASURES, MODEL_SEMANTIC_MODEL, etc.
        env_key = field_name.upper()  # e.g. "MODEL_DAX_MEASURES"
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val

        # Use the per-agent field value from the dataclass
        return getattr(self, field_name, self.default_model)

    def get_backend_for_model(self, model: str) -> str:
        """Look up the backend type for a model deployment name.

        Returns ``"responses"`` if the model is not found in the mapping.
        """
        return self.model_backends.get(model, "responses")


def get_agent_settings() -> AgentSettings:
    """Build ``AgentSettings`` from environment variables.

    The project endpoint and API key are read from ``PROJECT_ENDPOINT``
    and ``PROJECT_API_KEY`` respectively.  ``DefaultAzureCredential`` is
    used for authentication so the API key is typically not required.

    Concurrency settings can be tuned via environment variables:
    ``PAGE_GENERATION_WORKERS``, ``PAGE_LAUNCH_STAGGER_SECONDS``,
    ``MAX_CONCURRENT_LLM_CALLS``, and
    ``FUNCTIONAL_DOC_INPUT_THRESHOLD_KB``.
    """
    overrides: dict[str, object] = {}

    workers_env = os.environ.get("PAGE_GENERATION_WORKERS")
    if workers_env:
        overrides["page_generation_workers"] = int(workers_env)

    stagger_env = os.environ.get("PAGE_LAUNCH_STAGGER_SECONDS")
    if stagger_env:
        overrides["page_launch_stagger_seconds"] = float(stagger_env)

    concurrent_env = os.environ.get("MAX_CONCURRENT_LLM_CALLS")
    if concurrent_env:
        overrides["max_concurrent_llm_calls"] = int(concurrent_env)

    funcdoc_threshold_env = os.environ.get("FUNCTIONAL_DOC_INPUT_THRESHOLD_KB")
    if funcdoc_threshold_env:
        overrides["functional_doc_input_threshold_kb"] = int(funcdoc_threshold_env)

    tdd_max_tokens_env = os.environ.get("TDD_MAX_PROMPT_TOKENS")
    if tdd_max_tokens_env:
        overrides["tdd_max_prompt_tokens"] = int(tdd_max_tokens_env)

    return AgentSettings(
        project_endpoint=os.environ.get("PROJECT_ENDPOINT", _DEFAULT_ENDPOINT),
        tenant_id=os.environ.get("AZURE_TENANT_ID", ""),
        **overrides,  # type: ignore[arg-type]
    )


# ═══════════════════════════════════════════════════════════════════════════
# Shared constants — PBIP schema URLs and TMDL formatting
# ═══════════════════════════════════════════════════════════════════════════

# Power BI uses these ``$schema`` values to validate metadata files.  They
# must match the exact versions that PBI Desktop writes, otherwise the
# project may fail to open.

SCHEMA_PLATFORM = (
    "https://developer.microsoft.com/json-schemas" "/fabric/gitIntegration/platformProperties/2.0.0/schema.json"
)

SCHEMA_PBIR = (
    "https://developer.microsoft.com/json-schemas" "/fabric/item/report/definitionProperties/2.0.0/schema.json"
)

SCHEMA_PBISM = (
    "https://developer.microsoft.com/json-schemas" "/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json"
)

SCHEMA_EDITOR = (
    "https://developer.microsoft.com/json-schemas" "/fabric/item/semanticModel/editorSettings/1.0.0/schema.json"
)

SCHEMA_LOCAL = (
    "https://developer.microsoft.com/json-schemas" "/fabric/item/semanticModel/localSettings/1.2.0/schema.json"
)

# TMDL uses literal TAB characters for indentation (not spaces).  This is a
# hard requirement from the Power BI TMDL parser.
TAB = "\t"
