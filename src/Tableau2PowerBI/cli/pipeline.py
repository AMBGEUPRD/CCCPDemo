"""Tableau workbook analysis pipeline.

Runs three phases:

Phase 0 — Extract metadata from a .twb/.twbx file     (sequential)
Phase 1 — Generate functional documentation            (sequential)
Phase 2 — Generate target technical documentation      (sequential)
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent
from Tableau2PowerBI.agents.metadata_extractor import TableauMetadataExtractorAgent
from Tableau2PowerBI.agents.target_technical_doc import TargetTechnicalDocAgent
from Tableau2PowerBI.core.backends import shared_client_cache
from Tableau2PowerBI.core.config import AgentSettings, get_agent_settings
from Tableau2PowerBI.core.run_history import (
    STAGE_GRAPH,
    RunHistory,
    RunManifest,
    StageStatus,
    compute_input_hash,
    resolve_stages_to_run,
)
from Tableau2PowerBI.core.token_tracker import token_tracker
from Tableau2PowerBI.core.output_dirs import get_output_dir

logger = logging.getLogger(__name__)

StageCallable = Callable[[], Any]
AsyncStageCallable = Callable[[], Awaitable[None]]
SyncAgentRunner = Callable[[Any], Any]
AsyncAgentRunner = Callable[[Any], Awaitable[Any]]


class MigrationPipeline:
    """Orchestrates the Tableau workbook analysis pipeline.

    Runs three stages (extract → functional doc → TDD) and returns the
    TDD output directory for downstream use.

    Usage::

        pipeline = MigrationPipeline("data/input/Supermercato.twbx")
        output_dir = pipeline.run()
    """

    _AGENT_DIR_MAP: dict[str, str] = {
        "metadata_extractor": "tableau_metadata_extractor_agent",
        "functional_doc": "tableau_functional_doc_agent",
        "target_technical_doc": "target_technical_doc_agent",
    }

    def __init__(
        self,
        twb_path: str,
        semantic_model_name: str | None = None,
        settings: AgentSettings | None = None,
        *,
        resume_run_id: str | None = None,
        force_stages: set[str] | None = None,
    ) -> None:
        self.resolved_path = Path(twb_path).resolve()
        if not self.resolved_path.exists():
            raise FileNotFoundError(f"Workbook not found: {self.resolved_path}")

        self.workbook_name = self.resolved_path.stem
        self.semantic_model_name = semantic_model_name or self.workbook_name
        self.settings = settings or get_agent_settings()
        self._resume_run_id = resume_run_id
        self._force_stages = force_stages
        self._manifest_lock = threading.Lock()
        self._history = RunHistory(
            runs_root=self.settings.runs_root,
            output_root=self.settings.output_root,
            max_runs_per_workbook=self.settings.max_runs_per_workbook,
        )

    def run(self) -> Path:
        """Execute all pipeline phases and return the output directory."""
        pipeline_start = time.monotonic()
        token_tracker.reset()

        try:
            return self._run_phases(pipeline_start)
        finally:
            shared_client_cache.close_all()

    async def run_async(self) -> Path:
        """Async version of :meth:`run`."""
        pipeline_start = time.monotonic()
        token_tracker.reset()

        try:
            return await self._run_phases_async(pipeline_start)
        finally:
            await shared_client_cache.close_all_async()
            shared_client_cache.close_all()

    def _run_phases(self, pipeline_start: float) -> Path:
        """Execute all pipeline phases (called by :meth:`run`)."""
        manifest = self._load_or_create_manifest()
        current_hashes = self._build_current_hashes()
        stages_to_run = resolve_stages_to_run(
            manifest,
            current_hashes=current_hashes,
            force_stages=self._force_stages,
        )
        logger.info(
            "Stages to run: %s",
            ", ".join(sorted(stages_to_run)) or "(all cached)",
        )

        self._run_managed_stage(
            "P0",
            "Extracting Tableau metadata",
            "metadata_extractor",
            self._extract,
            manifest,
            stages_to_run,
        )

        self._run_managed_stage(
            "P1",
            "Functional documentation",
            "functional_doc",
            self._functional_doc,
            manifest,
            stages_to_run,
        )

        self._run_managed_stage(
            "P2",
            "Target technical documentation (TDD)",
            "target_technical_doc",
            self._target_technical_doc,
            manifest,
            stages_to_run,
        )

        output_dir = get_output_dir("target_technical_doc_agent", self.workbook_name, self.settings)

        ran_stages = stages_to_run & set(STAGE_GRAPH.keys())
        if ran_stages:
            self._history.mark_overwritten(
                self.workbook_name,
                ran_stages,
                exclude_run_id=manifest.run_id,
            )
        self._history.cleanup_old_runs(self.workbook_name)

        total = time.monotonic() - pipeline_start
        self._log_combined_tokens(manifest)
        logger.info("═══ Pipeline complete in %.1fs ═══", total)
        logger.info("Run ID: %s", manifest.run_id)
        logger.info("Output: %s", output_dir)
        return output_dir

    async def _run_phases_async(self, pipeline_start: float) -> Path:
        """Async version of :meth:`_run_phases`."""
        manifest = self._load_or_create_manifest()
        current_hashes = self._build_current_hashes()
        stages_to_run = resolve_stages_to_run(
            manifest,
            current_hashes=current_hashes,
            force_stages=self._force_stages,
        )
        logger.info(
            "Stages to run: %s",
            ", ".join(sorted(stages_to_run)) or "(all cached)",
        )

        if "metadata_extractor" in stages_to_run:
            logger.info("═══ P0: Extracting Tableau metadata ═══")
            await asyncio.to_thread(self._extract)
            self._record_stage(manifest, "metadata_extractor")
        else:
            logger.info("═══ P0 skipped (cached) ═══")

        if "functional_doc" in stages_to_run:
            logger.info("═══ P1: Functional documentation ═══")
            await self._functional_doc_async()
            self._record_stage(manifest, "functional_doc")
        else:
            logger.info("═══ P1 skipped (cached) ═══")

        if "target_technical_doc" in stages_to_run:
            logger.info("═══ P2: Target technical documentation ═══")
            await self._target_technical_doc_async()
            self._record_stage(manifest, "target_technical_doc")
        else:
            logger.info("═══ P2 skipped (cached) ═══")

        output_dir = get_output_dir("target_technical_doc_agent", self.workbook_name, self.settings)

        ran_stages = stages_to_run & set(STAGE_GRAPH.keys())
        if ran_stages:
            self._history.mark_overwritten(
                self.workbook_name,
                ran_stages,
                exclude_run_id=manifest.run_id,
            )
        self._history.cleanup_old_runs(self.workbook_name)

        total = time.monotonic() - pipeline_start
        self._log_combined_tokens(manifest)
        logger.info("═══ Pipeline complete in %.1fs ═══", total)
        logger.info("Run ID: %s", manifest.run_id)
        logger.info("Output: %s", output_dir)
        return output_dir

    def _record_stage(self, manifest: RunManifest, stage_name: str) -> None:
        """Record a completed stage in the manifest (used by async path)."""
        info = STAGE_GRAPH.get(stage_name)
        self._history.update_stage(
            manifest,
            stage_name,
            status=StageStatus.COMPLETED,
            duration_seconds=0.0,
            deterministic=info.deterministic if info else True,
            input_tokens=token_tracker.total_tokens_in(),
            output_tokens=token_tracker.total_tokens_out(),
        )
        agent_dir = self._AGENT_DIR_MAP.get(stage_name)
        if agent_dir:
            self._history.store_artifacts(manifest, agent_dir)

    async def _functional_doc_async(self) -> None:
        """Async Stage: Generate functional documentation."""
        await self._run_stage_with_agent_async(
            FunctionalDocAgent,
            lambda doc_agent: doc_agent.generate_documentation_async(self.workbook_name),
            create_agent=True,
        )

    async def _target_technical_doc_async(self) -> None:
        """Async Stage: Generate target technical documentation."""
        await self._run_stage_with_agent_async(
            TargetTechnicalDocAgent,
            lambda tdd_agent: tdd_agent.generate_tdd_async(self.workbook_name),
            create_agent=True,
        )

    def _load_or_create_manifest(self) -> RunManifest:
        """Load an existing run manifest or create a fresh one."""
        if self._resume_run_id:
            manifest = self._history.load_run(
                self.workbook_name,
                self._resume_run_id,
            )
            logger.info("Resuming run %s", manifest.run_id)
            self._history.restore_run(manifest)
            return manifest

        return self._history.create_run(
            self.workbook_name,
            str(self.resolved_path),
        )

    def _run_managed_stage(
        self,
        label: str,
        description: str,
        stage_name: str,
        fn: StageCallable,
        manifest: RunManifest,
        stages_to_run: set[str],
    ) -> Any:
        """Run a stage if it's in the execution set; otherwise skip."""
        if stage_name not in stages_to_run:
            logger.info(
                "═══ Stage %s: %s — skipped (cached) ═══",
                label,
                description,
            )
            return None

        logger.info("═══ Stage %s: %s ═══", label, description)
        stage_start = time.monotonic()
        result = fn()
        elapsed = time.monotonic() - stage_start

        info = STAGE_GRAPH.get(stage_name)
        self._history.update_stage(
            manifest,
            stage_name,
            status=StageStatus.COMPLETED,
            duration_seconds=elapsed,
            deterministic=info.deterministic if info else True,
            input_tokens=token_tracker.total_tokens_in(),
            output_tokens=token_tracker.total_tokens_out(),
        )

        agent_dir = self._AGENT_DIR_MAP.get(stage_name)
        if agent_dir:
            self._history.store_artifacts(manifest, agent_dir)

        logger.info("Stage %s completed in %.1fs", label, elapsed)
        return result

    def _build_current_hashes(self) -> dict[str, str]:
        """Compute current input hashes for each pipeline stage."""
        extractor_dir = get_output_dir(
            "tableau_metadata_extractor_agent",
            self.workbook_name,
            self.settings,
        )
        functional_doc_dir = get_output_dir(
            "tableau_functional_doc_agent",
            self.workbook_name,
            self.settings,
        )

        return {
            "metadata_extractor": compute_input_hash([self.resolved_path]),
            "functional_doc": compute_input_hash(
                [
                    extractor_dir / "semantic_model_input.json",
                    extractor_dir / "report_input.json",
                ]
            ),
            "target_technical_doc": compute_input_hash(
                [
                    extractor_dir / "semantic_model_input.json",
                    extractor_dir / "report_input.json",
                    functional_doc_dir / "functional_documentation.json",
                ]
            ),
        }

    def _log_combined_tokens(self, manifest: RunManifest) -> None:
        """Log token totals: manifest (skipped) + live (just ran)."""
        token_tracker.log_summary()
        stored_in = sum(r.input_tokens for r in manifest.stages.values() if r.status == StageStatus.COMPLETED)
        stored_out = sum(r.output_tokens for r in manifest.stages.values() if r.status == StageStatus.COMPLETED)
        if stored_in or stored_out:
            logger.info(
                "Resumed stages tokens: in=%d  out=%d",
                stored_in,
                stored_out,
            )

    def _run_stage_with_agent(
        self,
        agent_cls: type[Any],
        runner: SyncAgentRunner,
        *,
        create_agent: bool = False,
    ) -> Any:
        """Run a sync stage inside an agent context manager."""
        with agent_cls(settings=self.settings) as agent:
            if create_agent:
                agent.create()
            return runner(agent)

    async def _run_stage_with_agent_async(
        self,
        agent_cls: type[Any],
        runner: AsyncAgentRunner,
        *,
        create_agent: bool = False,
    ) -> Any:
        """Run an async stage inside an async agent context manager."""
        async with agent_cls(settings=self.settings) as agent:
            if create_agent:
                agent.create()
            return await runner(agent)

    def _extract(self) -> None:
        """Stage P0: Parse the Tableau workbook into metadata JSON."""
        self._run_stage_with_agent(
            TableauMetadataExtractorAgent,
            lambda extractor: extractor.extract_tableau_metadata(str(self.resolved_path)),
        )

    def _functional_doc(self) -> None:
        """Stage P1: Generate functional documentation of the workbook."""
        self._run_stage_with_agent(
            FunctionalDocAgent,
            lambda doc_agent: doc_agent.generate_documentation(self.workbook_name),
            create_agent=True,
        )

    def _target_technical_doc(self) -> None:
        """Stage P2: Generate target technical documentation."""
        self._run_stage_with_agent(
            TargetTechnicalDocAgent,
            lambda tdd_agent: tdd_agent.generate_tdd(self.workbook_name),
            create_agent=True,
        )

    @staticmethod
    def _run_stage(label: str, description: str, fn: StageCallable) -> Any:
        """Run a stage function with timing and formatted log output."""
        logger.info("═══ Stage %s: %s ═══", label, description)
        stage_start = time.monotonic()
        result = fn()
        logger.info("Stage %s completed in %.1fs", label, time.monotonic() - stage_start)
        return result


_MODEL_SHORT_NAMES: dict[str, str] = {
    "target_technical_doc": "model_target_technical_doc",
    "functional_doc": "model_functional_doc",
    "warnings_reviewer": "model_warnings_reviewer",
}


def build_settings(models_json: str | None) -> AgentSettings:
    """Build ``AgentSettings`` with optional per-agent model overrides."""
    overrides: dict[str, str] = {}
    if models_json:
        raw = json.loads(models_json)
        for short_name, model in raw.items():
            field_name = _MODEL_SHORT_NAMES.get(short_name)
            if field_name is None:
                raise ValueError(
                    f"Unknown agent short name '{short_name}'. " f"Valid names: {', '.join(sorted(_MODEL_SHORT_NAMES))}"
                )
            overrides[field_name] = model

    base = get_agent_settings()
    if not overrides:
        return base

    merged = {**asdict(base), **overrides}
    return AgentSettings(**merged)


def run_pipeline(
    twb_path: str,
    semantic_model_name: str | None = None,
    settings: AgentSettings | None = None,
    *,
    resume_run_id: str | None = None,
    force_stages: set[str] | None = None,
) -> Path:
    """Run the Tableau workbook analysis pipeline."""
    pipeline = MigrationPipeline(
        twb_path,
        semantic_model_name,
        settings,
        resume_run_id=resume_run_id,
        force_stages=force_stages,
    )
    return pipeline.run()


async def run_pipeline_async(
    twb_path: str,
    semantic_model_name: str | None = None,
    settings: AgentSettings | None = None,
    *,
    resume_run_id: str | None = None,
    force_stages: set[str] | None = None,
) -> Path:
    """Async version of :func:`run_pipeline`."""
    pipeline = MigrationPipeline(
        twb_path,
        semantic_model_name,
        settings,
        resume_run_id=resume_run_id,
        force_stages=force_stages,
    )
    return await pipeline.run_async()
