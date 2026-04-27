"""End-to-end Tableau → Power BI migration pipeline.

Runs five phases with parallelism where safe:

Phase 0 — Extract metadata from a .twb/.twbx file                 (sequential)
Phase 1 — Generate functional doc + project skeleton               (parallel)
Phase 2 — Generate target technical documentation (TDD)            (sequential)
Phase 3 — Generate semantic model, DAX measures, report visuals    (parallel)
Phase 4 — Assemble the final PBIP project                          (sequential)

Phases 1 and 3 use ``ThreadPoolExecutor`` because each agent spawns its
own Azure SDK client and both the network I/O and the underlying calls
release the GIL. The assembler in phase 4 is deterministic Python that
merges outputs from phases 3 and 4.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from Tableau2PowerBI.agents.assembler import PBIPProjectAssemblerAgent
from Tableau2PowerBI.agents.dax_measures import TmdlMeasuresGeneratorAgent
from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent
from Tableau2PowerBI.agents.metadata_extractor import TableauMetadataExtractorAgent
from Tableau2PowerBI.agents.report_visuals import PbirReportGeneratorAgent
from Tableau2PowerBI.agents.semantic_model import PBIPSemanticModelGeneratorAgent
from Tableau2PowerBI.agents.skeleton import PBIPProjectSkeletonAgent
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
from Tableau2PowerBI.core.source_detection import detect_source_file
from Tableau2PowerBI.core.token_tracker import token_tracker
from Tableau2PowerBI.core.output_dirs import get_output_dir

logger = logging.getLogger(__name__)

StageCallable = Callable[[], Any]
AsyncStageCallable = Callable[[], Awaitable[None]]
ParallelTask = tuple[str, str, StageCallable]
SyncAgentRunner = Callable[[Any], Any]
AsyncAgentRunner = Callable[[Any], Awaitable[Any]]


class MigrationPipeline:
    """Orchestrates the full Tableau → PBIP conversion pipeline.

    Encapsulates the eight-stage flow (extract → functional doc → TDD
    → skeleton → semantic model → DAX measures → visuals → assemble)
    with timing instrumentation and clean logging.

    Usage::

        pipeline = MigrationPipeline("data/input/Supermercato.twbx")
        output_dir = pipeline.run()
    """

    _AGENT_DIR_MAP: dict[str, str] = {
        "metadata_extractor": "tableau_metadata_extractor_agent",
        "functional_doc": "tableau_functional_doc_agent",
        "skeleton": "pbip_project_skeleton_agent",
        "target_technical_doc": "target_technical_doc_agent",
        "semantic_model": "pbip_semantic_model_generator_agent",
        "dax_measures": "tmdl_measures_generator_agent",
        "report_visuals": "pbir_report_generator_agent",
        "assembler": "pbip_project_assembler_agent",
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
        detected = detect_source_file(self.resolved_path)
        if detected.source_format != "tableau":
            raise ValueError(
                "PBIP ZIP inputs are analyze-only in v1. Use metadata extraction instead of the migration pipeline."
            )

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

        p1_tasks = [
            (label, name, self._wrap_stage(name, fn, manifest))
            for label, name, fn in [
                ("P1a", "functional_doc", self._functional_doc),
                ("P1b", "skeleton", self._skeleton),
            ]
            if name in stages_to_run
        ]
        if p1_tasks:
            self._run_parallel_phase(
                "P1",
                "Functional documentation + project skeleton",
                p1_tasks,
            )
        else:
            logger.info("═══ Phase P1 skipped (cached) ═══")

        self._run_managed_stage(
            "P2",
            "Target technical documentation (TDD)",
            "target_technical_doc",
            self._target_technical_doc,
            manifest,
            stages_to_run,
        )

        p3_tasks = [
            (label, name, self._wrap_stage(name, fn, manifest))
            for label, name, fn in [
                ("P3a", "semantic_model", self._semantic_model),
                ("P3b", "dax_measures", self._dax_measures),
                ("P3c", "report_visuals", self._visuals),
            ]
            if name in stages_to_run
        ]
        if p3_tasks:
            self._run_parallel_phase(
                "P3",
                "Semantic model + DAX measures + report visuals",
                p3_tasks,
            )
        else:
            logger.info("═══ Phase P3 skipped (cached) ═══")

        output_dir = self._run_managed_stage(
            "P4",
            "Assembling final PBIP project",
            "assembler",
            self._assemble,
            manifest,
            stages_to_run,
        )
        if output_dir is None:
            output_dir = get_output_dir(
                "pbip_project_assembler_agent",
                self.workbook_name,
                self.settings,
            )

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

        p1: dict[str, AsyncStageCallable] = {
            "functional_doc": self._functional_doc_async,
            "skeleton": lambda: asyncio.to_thread(self._skeleton),
        }
        await self._run_parallel_phase_async(
            "P1",
            "Functional doc + skeleton",
            p1,
            manifest,
            stages_to_run,
        )

        if "target_technical_doc" in stages_to_run:
            logger.info("═══ P2: Target technical documentation ═══")
            await self._target_technical_doc_async()
            self._record_stage(manifest, "target_technical_doc")
        else:
            logger.info("═══ P2 skipped (cached) ═══")

        p3: dict[str, AsyncStageCallable] = {
            "semantic_model": self._semantic_model_async,
            "dax_measures": self._dax_measures_async,
            "report_visuals": self._visuals_async,
        }
        await self._run_parallel_phase_async(
            "P3",
            "Semantic model + DAX + visuals",
            p3,
            manifest,
            stages_to_run,
        )

        if "assembler" in stages_to_run:
            logger.info("═══ P4: Assembling final PBIP project ═══")
            output_dir = await asyncio.to_thread(self._assemble)
            self._record_stage(manifest, "assembler")
        else:
            logger.info("═══ P4 skipped (cached) ═══")
            output_dir = get_output_dir(
                "pbip_project_assembler_agent",
                self.workbook_name,
                self.settings,
            )

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

    async def _run_parallel_phase_async(
        self,
        phase_label: str,
        phase_description: str,
        stage_map: dict[str, AsyncStageCallable],
        manifest: RunManifest,
        stages_to_run: set[str],
    ) -> None:
        """Run stages in *stage_map* concurrently using TaskGroup."""
        to_run = {k: v for k, v in stage_map.items() if k in stages_to_run}
        if not to_run:
            logger.info("═══ Phase %s skipped (cached) ═══", phase_label)
            return

        logger.info("═══ Phase %s: %s ═══", phase_label, phase_description)
        phase_start = time.monotonic()
        errors: list[tuple[str, Exception]] = []
        tasks: dict[str, asyncio.Task[None]] = {}

        try:
            async with asyncio.TaskGroup() as tg:
                for name, coro_fn in to_run.items():
                    logger.info("  ├─ Starting %s", name)
                    tasks[name] = tg.create_task(coro_fn())
        except* Exception as eg:
            for exc in eg.exceptions:
                for name, task in tasks.items():
                    if task.done() and task.exception() is exc:
                        errors.append((name, exc))
                        break

        for name, task in tasks.items():
            if task.done() and not task.cancelled() and task.exception() is None:
                logger.info("  ├─ %s completed", name)
                self._record_stage(manifest, name)

        for name, exc in errors:
            logger.error("  ├─ %s FAILED: %s", name, exc)

        elapsed = time.monotonic() - phase_start
        logger.info(
            "Phase %s completed in %.1fs (%d/%d tasks succeeded)",
            phase_label,
            elapsed,
            len(to_run) - len(errors),
            len(to_run),
        )

        if errors:
            labels = ", ".join(lbl for lbl, _ in errors)
            raise RuntimeError(
                f"Phase {phase_label} failed — {len(errors)} task(s) errored: {labels}",
            ) from errors[
                0
            ][1]

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

    async def _semantic_model_async(self) -> None:
        """Async Stage: Generate the semantic model."""
        await self._run_stage_with_agent_async(
            PBIPSemanticModelGeneratorAgent,
            lambda sm_agent: sm_agent.generate_pbip_semantic_model_async(
                self.workbook_name,
                semantic_model_name=self.semantic_model_name,
            ),
            create_agent=True,
        )

    async def _dax_measures_async(self) -> None:
        """Async Stage: Generate DAX measures."""
        await self._run_stage_with_agent_async(
            TmdlMeasuresGeneratorAgent,
            lambda dax_agent: dax_agent.generate_tmdl_measures_async(self.workbook_name),
            create_agent=True,
        )

    async def _visuals_async(self) -> None:
        """Async Stage: Generate PBIR report visuals."""
        await self._run_stage_with_agent_async(
            PbirReportGeneratorAgent,
            lambda visuals_agent: visuals_agent.generate_pbir_report_async(self.workbook_name),
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
        tdd_dir = get_output_dir(
            "target_technical_doc_agent",
            self.workbook_name,
            self.settings,
        )
        skeleton_dir = get_output_dir(
            "pbip_project_skeleton_agent",
            self.workbook_name,
            self.settings,
        )
        semantic_model_dir = get_output_dir(
            "pbip_semantic_model_generator_agent",
            self.workbook_name,
            self.settings,
        )
        dax_dir = get_output_dir(
            "tmdl_measures_generator_agent",
            self.workbook_name,
            self.settings,
        )
        visuals_dir = get_output_dir(
            "pbir_report_generator_agent",
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
            "skeleton": compute_input_hash([self.resolved_path]),
            "target_technical_doc": compute_input_hash(
                [
                    extractor_dir / "semantic_model_input.json",
                    extractor_dir / "report_input.json",
                    functional_doc_dir / "functional_documentation.json",
                ]
            ),
            "semantic_model": compute_input_hash([tdd_dir]),
            "dax_measures": compute_input_hash([tdd_dir]),
            "report_visuals": compute_input_hash([tdd_dir]),
            "assembler": compute_input_hash(
                [
                    skeleton_dir,
                    semantic_model_dir,
                    dax_dir,
                    visuals_dir,
                ]
            ),
        }

    def _wrap_stage(self, stage_name: str, fn: StageCallable, manifest: RunManifest) -> StageCallable:
        """Return a callable that runs *fn* and records completion."""
        lock = self._manifest_lock

        def _wrapped() -> Any:
            stage_start = time.monotonic()
            result = fn()
            elapsed = time.monotonic() - stage_start
            info = STAGE_GRAPH.get(stage_name)
            with lock:
                self._history.update_stage(
                    manifest,
                    stage_name,
                    status=StageStatus.COMPLETED,
                    duration_seconds=elapsed,
                    deterministic=info.deterministic if info else True,
                )
                agent_dir = self._AGENT_DIR_MAP.get(stage_name)
                if agent_dir:
                    self._history.store_artifacts(manifest, agent_dir)
            return result

        return _wrapped

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
        """Stage 1: Parse the Tableau workbook into metadata JSON."""
        self._run_stage_with_agent(
            TableauMetadataExtractorAgent,
            lambda extractor: extractor.extract_tableau_metadata(str(self.resolved_path)),
        )

    def _functional_doc(self) -> None:
        """Stage 2: Generate functional documentation of the workbook."""
        self._run_stage_with_agent(
            FunctionalDocAgent,
            lambda doc_agent: doc_agent.generate_documentation(self.workbook_name),
            create_agent=True,
        )

    def _target_technical_doc(self) -> None:
        """Stage 3: Generate target technical documentation."""
        self._run_stage_with_agent(
            TargetTechnicalDocAgent,
            lambda tdd_agent: tdd_agent.generate_tdd(self.workbook_name),
            create_agent=True,
        )

    def _skeleton(self) -> None:
        """Stage 4: Create the empty PBIP project scaffold."""
        self._run_stage_with_agent(
            PBIPProjectSkeletonAgent,
            lambda skeleton_agent: skeleton_agent.generate_pbip_project_skeleton(
                self.workbook_name,
                report_name=self.workbook_name,
                semantic_model_name=self.semantic_model_name,
            ),
        )

    def _semantic_model(self) -> None:
        """Stage 5: Call the LLM to generate the semantic model."""
        self._run_stage_with_agent(
            PBIPSemanticModelGeneratorAgent,
            lambda sm_agent: sm_agent.generate_pbip_semantic_model(
                self.workbook_name,
                semantic_model_name=self.semantic_model_name,
            ),
            create_agent=True,
        )

    def _dax_measures(self) -> None:
        """Stage 6: Call the LLM to generate DAX measures."""
        self._run_stage_with_agent(
            TmdlMeasuresGeneratorAgent,
            lambda dax_agent: dax_agent.generate_tmdl_measures(self.workbook_name),
            create_agent=True,
        )

    def _visuals(self) -> None:
        """Stage 7: Call the LLM to generate PBIR report visuals."""
        self._run_stage_with_agent(
            PbirReportGeneratorAgent,
            lambda visuals_agent: visuals_agent.generate_pbir_report(self.workbook_name),
            create_agent=True,
        )

    def _assemble(self) -> Path:
        """Stage 8: Merge pipeline outputs into the final PBIP project."""
        return self._run_stage_with_agent(
            PBIPProjectAssemblerAgent,
            lambda assembler: assembler.assemble_pbip_project(self.workbook_name),
        )

    @staticmethod
    def _run_stage(label: str, description: str, fn: StageCallable) -> Any:
        """Run a stage function with timing and formatted log output."""
        logger.info("═══ Stage %s: %s ═══", label, description)
        stage_start = time.monotonic()
        result = fn()
        logger.info("Stage %s completed in %.1fs", label, time.monotonic() - stage_start)
        return result

    @staticmethod
    def _run_parallel_phase(
        phase_label: str,
        phase_description: str,
        tasks: list[ParallelTask],
    ) -> None:
        """Run multiple stages concurrently using ThreadPoolExecutor."""
        logger.info("═══ Phase %s: %s ═══", phase_label, phase_description)
        phase_start = time.monotonic()

        errors: list[tuple[str, Exception]] = []
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            future_to_label: dict[Any, tuple[str, str]] = {}
            for label, description, fn in tasks:
                logger.info("  ├─ Starting %s: %s", label, description)
                future = executor.submit(fn)
                future_to_label[future] = (label, description)

            for future in as_completed(future_to_label):
                label, _description = future_to_label[future]
                try:
                    future.result()
                    logger.info("  ├─ %s completed", label)
                except Exception as exc:
                    logger.error("  ├─ %s FAILED: %s", label, exc)
                    errors.append((label, exc))

        elapsed = time.monotonic() - phase_start
        logger.info(
            "Phase %s completed in %.1fs (%d/%d tasks succeeded)",
            phase_label,
            elapsed,
            len(tasks) - len(errors),
            len(tasks),
        )

        if errors:
            labels = ", ".join(lbl for lbl, _ in errors)
            raise RuntimeError(
                f"Phase {phase_label} failed — {len(errors)} task(s) errored: {labels}",
            ) from errors[
                0
            ][1]


_MODEL_SHORT_NAMES: dict[str, str] = {
    "semantic_model": "model_semantic_model",
    "dax_measures": "model_dax_measures",
    "report_visuals": "model_report_visuals",
    "target_technical_doc": "model_target_technical_doc",
    "report_skeleton": "model_report_skeleton",
    "report_page_visuals": "model_report_page_visuals",
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
    """Run the full Tableau → PBIP conversion pipeline."""
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
