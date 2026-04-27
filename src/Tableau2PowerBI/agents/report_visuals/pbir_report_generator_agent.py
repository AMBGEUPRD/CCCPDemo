"""PbirReportGeneratorAgent — Stage 5, PBIR report generator."""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import BaseModel, Field, model_validator

from Tableau2PowerBI.agents.report_page_visuals import (
    PageVisualsOutput,
    ReportPageVisualsAgent,
)
from Tableau2PowerBI.agents.report_skeleton import (
    ReportSkeleton,
    SkeletonPage,
    build_skeleton_from_tdd,
)
from Tableau2PowerBI.agents.report_visuals.orchestration import (
    assemble_report,
    filter_metadata_for_page,
    generate_static_files,
)
from Tableau2PowerBI.agents.report_visuals.output_io import (
    save_decisions,
    validate_completeness,
)
from Tableau2PowerBI.agents.report_visuals.parsing import (
    parse_response,
)
from Tableau2PowerBI.agents.report_visuals.pipeline_inputs import (
    build_schema_from_tdd_sections,
    load_tdd_sections,
)
from Tableau2PowerBI.core.agent import Agent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.models import MigrationWarning
from Tableau2PowerBI.core.prompt_utils import compact_json
from Tableau2PowerBI.core.output_dirs import ensure_output_dir, get_output_dir, reset_output_dir

# Metadata keys in the agent response that are NOT file paths.
_NON_FILE_KEYS = {"_warnings"}


class PbirReportDecisions(BaseModel):
    """Validated contract for the PBIR report generator output.

    ``files`` maps relative paths to file content strings.
    Must contain at least one file key.
    """

    files: dict[str, str]
    warnings: list[MigrationWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_has_files(self) -> PbirReportDecisions:
        if not self.files:
            raise ValueError("Response contains no file path keys")
        return self


def parse_decisions_response(response: str) -> PbirReportDecisions:
    """Parse, normalise, and validate the raw LLM response."""
    files, warnings = parse_response(response, _NON_FILE_KEYS)
    return PbirReportDecisions.model_validate({"files": files, "warnings": warnings})


class PbirReportGeneratorAgent(Agent):
    """Generate a Power BI PBIR report from Tableau worksheets/dashboards.

    Sends Tableau report metadata to the LLM, validates the response
    with Pydantic, retries with error feedback on validation failure,
    and writes the ``.Report/`` folder structure to disk.
    """

    def __init__(
        self,
        model: str | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        super().__init__(
            skill_name="pbir_report_generator_agent",
            model=model,
            settings=settings,
        )
        self.prompt_template = (
            "Parse this Tableau workbook report metadata JSON and generate a complete, "
            "valid Power BI .pbir report folder structure following the skill "
            "instructions precisely.\n\n"
            "Return a COMPACT flat JSON object (single line, no indentation) where "
            "every key is a relative file path and every value is the file content "
            "serialised as a COMPACT JSON string (no indentation inside values either).\n"
            "Include a '_warnings' key with a list of {{ severity, code, message }} "
            "objects for every visual that could not be fully translated.\n\n"
            "CRITICAL: Output must be a SINGLE LINE of valid JSON to avoid truncation. "
            "Do NOT pretty-print. Do NOT wrap in markdown fences.\n\n"
            "Workbook name: {workbook_name}\n\n"
        )

    # ── public entry point ────────────────────────────────────────────────────

    def generate_pbir_report(
        self,
        workbook_name: str,
        *,
        reset_output: bool = True,
    ) -> None:
        """Full pipeline: read TDD → build skeleton → generate visuals → save.

        Reads the Target Technical Documentation (TDD) as the single source
        of truth for report design, field bindings, and entity resolution.

        Uses the two-pass hybrid architecture:
        1. Build skeleton deterministically from TDD (no LLM).
        2. Page-parallel visual generation via LLM sub-agents.

        All boilerplate files (pages, bookmarks, report.json, etc.) are
        generated deterministically in code — the LLM only produces
        visual.json content.  The page-level sub-agent already applies
        structural fixes inline, so no post-processing chain is needed.
        """
        tdd_report, tdd_sm, tdd_dax = load_tdd_sections(
            workbook_name,
            self.settings,
            self.logger,
        )
        schema = build_schema_from_tdd_sections(tdd_sm, tdd_dax, tdd_report)

        report_metadata = compact_json(tdd_report)

        decisions = self._generate_hybrid(
            workbook_name,
            report_metadata,
            schema,
        )
        self.logger.info("Agent decisions received and validated.")

        output_dir = get_output_dir(self.skill_name, workbook_name, self.settings)
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        validate_completeness(decisions.files, workbook_name, self.logger)
        save_decisions(decisions.files, decisions.warnings, output_dir, self.logger)
        self.logger.info("PBIR report generation complete.")

    async def generate_pbir_report_async(
        self,
        workbook_name: str,
        *,
        reset_output: bool = True,
    ) -> None:
        """Async version of :meth:`generate_pbir_report`.

        Delegates to the sync implementation in a thread because this
        agent's internal page-parallel generation uses
        ``ThreadPoolExecutor`` with sub-agent objects.  Converting that
        to ``asyncio.TaskGroup`` is a separate task.
        """
        await asyncio.to_thread(
            self.generate_pbir_report,
            workbook_name,
            reset_output=reset_output,
        )

    # ── Hybrid two-pass generation ────────────────────────────────────────────

    def _generate_hybrid(
        self,
        workbook_name: str,
        report_metadata: str,
        schema_text: str,
    ) -> PbirReportDecisions:
        """Two-pass hybrid: skeleton → page-parallel visual generation.

        Pass 1: Build the skeleton deterministically from TDD report
        data.  The TDD already contains the full page/visual structure
        (visual types, positions, worksheet names), so no LLM call is
        needed for the skeleton.

        Pass 2: One page agent per page generates the visual.json content
        for all visuals on that page, running in parallel.

        The results are assembled into a PbirReportDecisions with both
        deterministic boilerplate files and LLM-generated visuals.
        """
        self.logger.info("Hybrid generation: building skeleton from TDD")

        # Pass 1: Build skeleton deterministically from TDD.
        report_input = json.loads(report_metadata)
        skeleton = build_skeleton_from_tdd(report_input)
        self.logger.info(
            "Built skeleton from TDD: %d pages, %d visuals",
            len(skeleton.pages),
            sum(len(page.visuals) for page in skeleton.pages),
        )

        total_visuals = sum(len(p.visuals) for p in skeleton.pages)
        self.logger.info(
            "Skeleton: %d pages, %d visual slots",
            len(skeleton.pages),
            total_visuals,
        )

        # Pass 2: Page-parallel visual generation.
        page_visuals = self._generate_all_pages(
            skeleton,
            workbook_name,
            report_input,
            schema_text,
        )

        # Log coverage summary.
        generated = sum(len(pv.visuals) for pv in page_visuals.values())
        self.logger.info(
            "Page generation: %d/%d visuals across %d/%d pages",
            generated,
            total_visuals,
            len(page_visuals),
            len(skeleton.pages),
        )

        # Assemble deterministic boilerplate + visual files.
        static_files = generate_static_files(skeleton, workbook_name)
        files, all_warnings = assemble_report(
            skeleton,
            page_visuals,
            workbook_name,
            static_files,
        )
        return PbirReportDecisions(files=files, warnings=all_warnings)

    # ── Page-parallel visual generation ───────────────────────────────────────

    def _generate_all_pages(
        self,
        skeleton: ReportSkeleton,
        workbook_name: str,
        report_input: dict,
        schema_text: str,
    ) -> dict[str, PageVisualsOutput]:
        """Generate visual content for all pages in parallel.

        Pre-creates agent instances in the main thread to avoid the
        ``self.runtime`` initialisation race, then dispatches page
        generation to a thread pool with staggered launches to
        reduce Azure 429 cascading.
        """
        pages = skeleton.pages
        total = len(pages)

        if total == 0:
            return {}

        # Pre-create all agents in the main thread.
        agents: list[ReportPageVisualsAgent] = []
        for i in range(total):
            agent = ReportPageVisualsAgent(settings=self.settings)
            agent.create()
            agents.append(agent)
            self.logger.info("Pre-created page agent %d/%d", i + 1, total)

        results: dict[str, PageVisualsOutput] = {}
        stagger = self.settings.page_launch_stagger_seconds

        def _generate_one(
            idx: int,
            page: SkeletonPage,
            agent: ReportPageVisualsAgent,
        ) -> tuple[str, PageVisualsOutput]:
            """Thread worker: generate visuals for one page."""
            try:
                # Emit structured sub-agent start event.
                self.logger.info(
                    "Page %d/%d — generating '%s'",
                    idx + 1,
                    total,
                    page.display_name,
                    extra={
                        "sub_agent": {
                            "agent_id": "pbip_visuals_generator",
                            "page_name": page.display_name,
                            "page_index": idx,
                            "page_total": total,
                            "state": "running",
                        },
                    },
                )
                filtered = filter_metadata_for_page(report_input, page)
                skeleton_page_json = page.model_dump_json()
                output = agent.generate_page_visuals(
                    workbook_name=workbook_name,
                    skeleton_page_json=skeleton_page_json,
                    page_worksheets_json=filtered,
                    schema_text=schema_text,
                )
                # Emit structured sub-agent done event.
                self.logger.info(
                    "Page %d/%d (%s) — %d visuals",
                    idx + 1,
                    total,
                    page.display_name,
                    len(output.visuals),
                    extra={
                        "sub_agent": {
                            "agent_id": "pbip_visuals_generator",
                            "page_name": page.display_name,
                            "page_index": idx,
                            "page_total": total,
                            "visuals_count": len(output.visuals),
                            "state": "done",
                        },
                    },
                )
                return page.hex_id, output
            finally:
                agent.close()

        workers = min(self.settings.page_generation_workers, total)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for idx, (page, agent) in enumerate(zip(pages, agents)):
                if idx > 0:
                    time.sleep(stagger)
                future = executor.submit(_generate_one, idx, page, agent)
                futures[future] = page

            for future in as_completed(futures):
                page = futures[future]
                try:
                    hex_id, output = future.result()
                    results[hex_id] = output
                except Exception:
                    # Determine page index for the structured event.
                    page_idx = next(
                        (i for i, p in enumerate(pages) if p.hex_id == page.hex_id),
                        -1,
                    )
                    self.logger.error(
                        "Page '%s' generation failed — skipping.",
                        page.display_name,
                        exc_info=True,
                        extra={
                            "sub_agent": {
                                "agent_id": "pbip_visuals_generator",
                                "page_name": page.display_name,
                                "page_index": page_idx,
                                "page_total": total,
                                "state": "error",
                            },
                        },
                    )

        return results
