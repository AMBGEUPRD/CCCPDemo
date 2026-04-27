"""Target Technical Documentation (TDD) Agent.

Analyses extracted Tableau metadata and functional documentation to
produce a structured technical blueprint for the target Power BI
implementation.  The TDD contains all design decisions — table inventory,
column mappings, DAX translation strategies, visual bindings — so
downstream generation agents can focus on producing correct artefacts
without re-analysing raw metadata.

The agent makes **two sequential LLM calls**:

1. **Data Model Design** — tables, columns, relationships, M query
   strategies, DAX measure translatability, migration assessment
2. **Report Design** — pages, visuals, field bindings resolved to
   Power BI names, entity resolution maps

Typical usage::

    from Tableau2PowerBI.agents.target_technical_doc import (
        TargetTechnicalDocAgent,
    )

    with TargetTechnicalDocAgent() as agent:
        agent.create()
        tdd = agent.generate_tdd("Supermercato")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from Tableau2PowerBI.agents.target_technical_doc.chunking import (
    build_dashboard_batches,
    build_datasource_batches,
    estimate_tokens,
    merge_data_model_results,
    merge_report_results,
    PromptBudgetError,
)
from Tableau2PowerBI.agents.target_technical_doc.models import (
    DataModelDesign,
    MigrationAssessment,
    ReportDesign,
    TargetTechnicalDocumentation,
)
from Tableau2PowerBI.agents.target_technical_doc.renderer import (
    render_html,
    render_markdown,
)
from Tableau2PowerBI.core.agent import Agent, ContextLengthExceededError
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.llm_output_parsing import strip_markdown_fences
from Tableau2PowerBI.core.output_dirs import ensure_output_dir, get_output_dir, reset_output_dir
from Tableau2PowerBI.core.prompt_utils import compact_json

_ModelT = TypeVar("_ModelT", bound=BaseModel)

logger = logging.getLogger(__name__)

# ── LLM response parsing helpers ──────────────────────────────────────
# Extracted as module-level functions so the sync and async validation
# wrappers can share them without duplicating closure definitions.


def _parse_llm_json_response(raw_response: str, model_cls: type[_ModelT]) -> _ModelT:
    """Parse a raw LLM response string into a validated Pydantic model.

    Args:
        raw_response: Raw text returned by the LLM.
        model_cls: The Pydantic model class to validate against.

    Returns:
        Validated instance of *model_cls*.

    Raises:
        ValueError: If the response is not valid JSON.
        ValidationError: If the JSON does not match the model schema.
    """
    clean = strip_markdown_fences(raw_response)
    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Response is not valid JSON: {exc}. "
            f"First 300 chars: {raw_response[:300]!r}"
        ) from exc
    return model_cls.model_validate(data)


def _format_validation_error(exc: Exception) -> str:
    """Format a parse or validation exception into a feedback string for retry."""
    if isinstance(exc, ValidationError):
        return json.dumps(exc.errors(), indent=2, ensure_ascii=False)
    return str(exc)


# ── Prompt prefixes ────────────────────────────────────────────────────

_CALL1_PREFIX = (
    "You are performing **Call 1 — Data Model & DAX Measures Design**.\n"
    "Analyse the Tableau metadata and functional documentation below, "
    "then return a structured JSON matching the Call 1 output schema "
    "described in your instructions.\n\n"
)

_CALL2_PREFIX = (
    "You are performing **Call 2 — Report Design**.\n"
    "Analyse the Tableau report metadata, functional documentation, and "
    "data model design (from Call 1) below, then return a structured "
    "JSON matching the Call 2 output schema described in your instructions.\n\n"
)

# ── Output filenames ───────────────────────────────────────────────────

SEMANTIC_MODEL_DESIGN_FILE = "semantic_model_design.json"
DAX_MEASURES_DESIGN_FILE = "dax_measures_design.json"
REPORT_DESIGN_FILE = "report_design.json"
MIGRATION_ASSESSMENT_FILE = "migration_assessment.json"
MD_FILENAME = "target_technical_documentation.md"
HTML_FILENAME = "target_technical_documentation.html"
FUNCTIONAL_DOC_JSON = "functional_documentation.json"


class TargetTechnicalDocAgent(Agent):
    """LLM-powered agent that produces a Target Technical Documentation.

    Reads metadata from Stage 1 and functional documentation from Stage 2,
    then produces a structured technical blueprint consumed by Stages 4–6.
    """

    def __init__(
        self,
        model: str | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        super().__init__(
            skill_name="target_technical_doc_agent",
            model=model,
            settings=settings,
        )

    # ── Public API ─────────────────────────────────────────────────────

    def generate_tdd(
        self,
        workbook_name: str,
        data_folder_path: str | None = None,
        *,
        reset_output: bool = True,
    ) -> TargetTechnicalDocumentation:
        """Generate the Target Technical Documentation.

        Args:
            workbook_name: Stem of the workbook file (no extension).
            data_folder_path: Optional path to a folder containing
                the input files.  When ``None``, files are read from
                the default output directories of upstream agents.

        Returns:
            The validated :class:`TargetTechnicalDocumentation` model.
        """
        self.logger.info(
            "Generating TDD for '%s'",
            workbook_name,
        )

        # ── Load inputs ───────────────────────────────────────────────
        sm_input = self._load_json(
            workbook_name,
            "semantic_model_input.json",
            "tableau_metadata_extractor_agent",
            data_folder_path,
        )
        report_input = self._load_json(
            workbook_name,
            "report_input.json",
            "tableau_metadata_extractor_agent",
            data_folder_path,
        )
        func_doc = self._load_functional_doc(
            workbook_name,
            data_folder_path,
        )

        # ── Call 1: Data Model Design ─────────────────────────────────
        self.logger.info("[TDD:PHASE] 1/2 Data Model Design - Creating semantic model and DAX measures")
        data_model = self._call1_data_model(sm_input, func_doc)

        # ── Call 2: Report Design ─────────────────────────────────────
        self.logger.info("[TDD:PHASE] 2/2 Report Design - Creating report layout and visuals")
        report = self._call2_report(
            report_input,
            func_doc,
            data_model,
        )

        # ── Merge into final TDD ──────────────────────────────────────
        tdd = TargetTechnicalDocumentation(
            semantic_model=data_model.semantic_model,
            dax_measures=data_model.dax_measures,
            report=report,
            assessment=self._merge_assessment(
                data_model.assessment,
                report,
            ),
        )

        # ── Save outputs ──────────────────────────────────────────────
        self._save_outputs(workbook_name, tdd, reset_output=reset_output)

        self.logger.info(
            "TDD generated: %d tables, %d measures, %d pages",
            len(tdd.semantic_model.tables),
            len(tdd.dax_measures.measures),
            len(tdd.report.pages),
        )
        return tdd

    async def generate_tdd_async(
        self,
        workbook_name: str,
        data_folder_path: str | None = None,
        *,
        reset_output: bool = True,
    ) -> "TargetTechnicalDocumentation":
        """Async version of :meth:`generate_tdd`."""
        self.logger.info("Generating TDD for '%s'", workbook_name)

        sm_input = self._load_json(
            workbook_name,
            "semantic_model_input.json",
            "tableau_metadata_extractor_agent",
            data_folder_path,
        )
        report_input = self._load_json(
            workbook_name,
            "report_input.json",
            "tableau_metadata_extractor_agent",
            data_folder_path,
        )
        func_doc = self._load_functional_doc(workbook_name, data_folder_path)

        # Call 1: Data Model Design
        self.logger.info("[TDD:PHASE] 1/2 Data Model Design - Creating semantic model and DAX measures")
        data_model = await self._call1_data_model_async(sm_input, func_doc)

        # Call 2: Report Design (depends on Call 1)
        self.logger.info("[TDD:PHASE] 2/2 Report Design - Creating report layout and visuals")
        report = await self._call2_report_async(report_input, func_doc, data_model)

        tdd = TargetTechnicalDocumentation(
            semantic_model=data_model.semantic_model,
            dax_measures=data_model.dax_measures,
            report=report,
            assessment=self._merge_assessment(data_model.assessment, report),
        )
        self._save_outputs(workbook_name, tdd, reset_output=reset_output)

        self.logger.info(
            "TDD generated: %d tables, %d measures, %d pages",
            len(tdd.semantic_model.tables),
            len(tdd.dax_measures.measures),
            len(tdd.report.pages),
        )
        return tdd

    # ── Call 1: Data Model Design ──────────────────────────────────────

    def _call1_data_model(
        self,
        sm_input: dict,
        func_doc: dict | None,
    ) -> DataModelDesign:
        """Run LLM Call 1 — single call when prompt fits, chunked otherwise.

        The full prompt is built first.  If its estimated token count is
        within budget, a single LLM call is attempted (with a try/except
        for cases where the token estimate under-counts).  If the prompt
        exceeds budget or the single call raises ContextLengthExceededError,
        the input is split into datasource batches and each batch is called
        separately, then results are merged.
        """
        prompt = self._build_call1_prompt(sm_input, func_doc)
        prompt_tokens = estimate_tokens(prompt)
        budget = self.settings.tdd_max_prompt_tokens

        # ── Single-call happy path ────────────────────────────────────
        if prompt_tokens <= budget:
            try:
                return self._run_with_validation(prompt, DataModelDesign, "Call 1 (data model)")
            except ContextLengthExceededError:
                self.logger.warning(
                    "Call 1: token estimate (%d) was within budget (%d) "
                    "but context exceeded — falling back to chunked path",
                    prompt_tokens,
                    budget,
                )

        # ── Chunked path ──────────────────────────────────────────────
        self.logger.warning(
            "Call 1: prompt ~%d tokens exceeds budget %d — splitting into batches",
            prompt_tokens,
            budget,
        )
        fixed_tokens = self._estimate_fixed_tokens_call1(func_doc)
        try:
            batches = build_datasource_batches(sm_input, budget, fixed_tokens)
        except PromptBudgetError:
            self.logger.warning(
                "Call 1: fixed overhead exceeds budget — fallback to single call"
            )
            return self._run_with_validation(prompt, DataModelDesign, "Call 1 (data model, fallback)")
        self.logger.info("Call 1: split into %d batch(es)", len(batches))

        partials: list[DataModelDesign] = []
        for i, batch in enumerate(batches):
            batch_prompt = self._build_call1_prompt(batch, func_doc)
            label = f"Call 1 batch {i + 1}/{len(batches)}"
            self.logger.info("Running %s", label)
            result = self._run_with_validation(batch_prompt, DataModelDesign, label)
            partials.append(result)

        return merge_data_model_results(partials, self.logger)

    async def _call1_data_model_async(
        self,
        sm_input: dict,
        func_doc: dict | None,
    ) -> DataModelDesign:
        """Async version of :meth:`_call1_data_model`."""
        prompt = self._build_call1_prompt(sm_input, func_doc)
        prompt_tokens = estimate_tokens(prompt)
        budget = self.settings.tdd_max_prompt_tokens

        if prompt_tokens <= budget:
            try:
                return await self._run_with_validation_async(
                    prompt, DataModelDesign, "Call 1 (data model)",
                )
            except ContextLengthExceededError:
                self.logger.warning(
                    "Call 1: token estimate (%d) was within budget (%d) "
                    "but context exceeded — falling back to chunked path",
                    prompt_tokens,
                    budget,
                )

        self.logger.warning(
            "Call 1: prompt ~%d tokens exceeds budget %d — splitting into batches",
            prompt_tokens,
            budget,
        )
        fixed_tokens = self._estimate_fixed_tokens_call1(func_doc)
        try:
            batches = build_datasource_batches(sm_input, budget, fixed_tokens)
        except PromptBudgetError:
            self.logger.warning(
                "Call 1: fixed overhead exceeds budget — fallback to single call"
            )
            return await self._run_with_validation_async(
                prompt, DataModelDesign, "Call 1 (data model, fallback)"
            )
        self.logger.info("Call 1: split into %d batch(es)", len(batches))

        partials: list[DataModelDesign] = []
        for i, batch in enumerate(batches):
            batch_prompt = self._build_call1_prompt(batch, func_doc)
            label = f"Call 1 batch {i + 1}/{len(batches)}"
            self.logger.info("Running %s", label)
            result = await self._run_with_validation_async(
                batch_prompt, DataModelDesign, label,
            )
            partials.append(result)

        return merge_data_model_results(partials, self.logger)

    def _build_call1_prompt(
        self,
        sm_input: dict,
        func_doc: dict | None,
    ) -> str:
        """Assemble the prompt for Call 1."""
        parts: list[str] = [_CALL1_PREFIX]

        # Inject functional doc context (if available)
        if func_doc:
            parts.append("## Functional Documentation\n")
            parts.append(compact_json(func_doc))
            parts.append("\n\n")

        # Inject semantic model input
        parts.append("## Tableau Metadata (semantic_model_input)\n")
        parts.append(compact_json(sm_input))

        return "".join(parts)

    def _estimate_fixed_tokens_call1(self, func_doc: dict | None) -> int:
        """Estimate tokens consumed by the fixed parts of a Call 1 prompt.

        Fixed parts include the prefix, section headers, and the
        functional documentation JSON (which is repeated in every batch).
        """
        prefix = estimate_tokens(_CALL1_PREFIX)
        headers = estimate_tokens(
            "## Functional Documentation\n\n\n"
            "## Tableau Metadata (semantic_model_input)\n"
        )
        func_doc_tokens = estimate_tokens(compact_json(func_doc)) if func_doc else 0
        return prefix + headers + func_doc_tokens

    # ── Call 2: Report Design ──────────────────────────────────────────

    def _call2_report(
        self,
        report_input: dict,
        func_doc: dict | None,
        data_model: DataModelDesign,
    ) -> ReportDesign:
        """Run LLM Call 2 — single call when prompt fits, chunked otherwise.

        Same strategy as :meth:`_call1_data_model` but splits by
        dashboards instead of datasources.
        """
        prompt = self._build_call2_prompt(report_input, func_doc, data_model)
        prompt_tokens = estimate_tokens(prompt)
        budget = self.settings.tdd_max_prompt_tokens

        # ── Single-call happy path ────────────────────────────────────
        if prompt_tokens <= budget:
            try:
                return self._run_with_validation(prompt, ReportDesign, "Call 2 (report)")
            except ContextLengthExceededError:
                self.logger.warning(
                    "Call 2: token estimate (%d) was within budget (%d) "
                    "but context exceeded — falling back to chunked path",
                    prompt_tokens,
                    budget,
                )

        # ── Chunked path ──────────────────────────────────────────────
        self.logger.warning(
            "Call 2: prompt ~%d tokens exceeds budget %d — splitting into batches",
            prompt_tokens,
            budget,
        )
        fixed_tokens = self._estimate_fixed_tokens_call2(func_doc, data_model)
        try:
            batches = build_dashboard_batches(report_input, budget, fixed_tokens)
        except PromptBudgetError:
            self.logger.warning(
                "Call 2: fixed overhead exceeds budget — fallback to single call"
            )
            return self._run_with_validation(prompt, ReportDesign, "Call 2 (report, fallback)")
        self.logger.info("Call 2: split into %d batch(es)", len(batches))

        partials: list[ReportDesign] = []
        for i, batch in enumerate(batches):
            batch_prompt = self._build_call2_prompt(batch, func_doc, data_model)
            label = f"Call 2 batch {i + 1}/{len(batches)}"
            self.logger.info("Running %s", label)
            result = self._run_with_validation(batch_prompt, ReportDesign, label)
            partials.append(result)

        return merge_report_results(partials, self.logger)

    async def _call2_report_async(
        self,
        report_input: dict,
        func_doc: dict | None,
        data_model: DataModelDesign,
    ) -> ReportDesign:
        """Async version of :meth:`_call2_report`."""
        prompt = self._build_call2_prompt(report_input, func_doc, data_model)
        prompt_tokens = estimate_tokens(prompt)
        budget = self.settings.tdd_max_prompt_tokens

        if prompt_tokens <= budget:
            try:
                return await self._run_with_validation_async(
                    prompt, ReportDesign, "Call 2 (report)",
                )
            except ContextLengthExceededError:
                self.logger.warning(
                    "Call 2: token estimate (%d) was within budget (%d) "
                    "but context exceeded — falling back to chunked path",
                    prompt_tokens,
                    budget,
                )

        self.logger.warning(
            "Call 2: prompt ~%d tokens exceeds budget %d — splitting into batches",
            prompt_tokens,
            budget,
        )
        fixed_tokens = self._estimate_fixed_tokens_call2(func_doc, data_model)
        try:
            batches = build_dashboard_batches(report_input, budget, fixed_tokens)
        except PromptBudgetError:
            self.logger.warning(
                "Call 2: fixed overhead exceeds budget — fallback to single call"
            )
            return await self._run_with_validation_async(
                prompt, ReportDesign, "Call 2 (report, fallback)"
            )
        self.logger.info("Call 2: split into %d batch(es)", len(batches))

        partials: list[ReportDesign] = []
        for i, batch in enumerate(batches):
            batch_prompt = self._build_call2_prompt(batch, func_doc, data_model)
            label = f"Call 2 batch {i + 1}/{len(batches)}"
            self.logger.info("Running %s", label)
            result = await self._run_with_validation_async(
                batch_prompt, ReportDesign, label,
            )
            partials.append(result)

        return merge_report_results(partials, self.logger)

    def _build_call2_prompt(
        self,
        report_input: dict,
        func_doc: dict | None,
        data_model: DataModelDesign,
    ) -> str:
        """Assemble the prompt for Call 2."""
        parts: list[str] = [_CALL2_PREFIX]

        # Inject functional doc context (if available)
        if func_doc:
            parts.append("## Functional Documentation\n")
            parts.append(compact_json(func_doc))
            parts.append("\n\n")

        # Inject data model design (from Call 1) — table names,
        # measure names, so report design can resolve field bindings
        parts.append("## Data Model Design (from Call 1)\n")
        dm_summary = data_model.model_dump(mode="json")
        parts.append(compact_json(dm_summary))
        parts.append("\n\n")

        # Inject report input
        parts.append("## Tableau Metadata (report_input)\n")
        parts.append(compact_json(report_input))

        return "".join(parts)

    def _estimate_fixed_tokens_call2(
        self,
        func_doc: dict | None,
        data_model: DataModelDesign,
    ) -> int:
        """Estimate tokens consumed by the fixed parts of a Call 2 prompt.

        Fixed parts include the prefix, section headers, functional
        documentation JSON, and the data model JSON (both repeated in
        every batch).
        """
        prefix = estimate_tokens(_CALL2_PREFIX)
        headers = estimate_tokens(
            "## Functional Documentation\n\n\n"
            "## Data Model Design (from Call 1)\n\n\n"
            "## Tableau Metadata (report_input)\n"
        )
        func_doc_tokens = estimate_tokens(compact_json(func_doc)) if func_doc else 0
        data_model_tokens = estimate_tokens(
            compact_json(data_model.model_dump(mode="json")),
        )
        return prefix + headers + func_doc_tokens + data_model_tokens

    # ── Shared LLM call with retry-with-feedback ──────────────────────

    def _run_with_validation(
        self,
        prompt: str,
        model_cls: type[_ModelT],
        label: str,
    ) -> _ModelT:
        """Call the LLM and validate the response as a Pydantic model."""
        return self.run_with_validation(
            prompt,
            lambda raw: _parse_llm_json_response(raw, model_cls),
            label=label,
            parse_exceptions=(ValidationError, ValueError),
            error_formatter=_format_validation_error,
        )

    async def _run_with_validation_async(
        self,
        prompt: str,
        model_cls: type[_ModelT],
        label: str,
    ) -> _ModelT:
        """Async version of :meth:`_run_with_validation`."""
        return await self.run_with_validation_async(
            prompt,
            lambda raw: _parse_llm_json_response(raw, model_cls),
            label=label,
            parse_exceptions=(ValidationError, ValueError),
            error_formatter=_format_validation_error,
        )

    # ── Input loading ──────────────────────────────────────────────────

    def _load_json(
        self,
        workbook_name: str,
        filename: str,
        agent_name: str,
        data_folder_path: str | None,
    ) -> dict:
        """Load a JSON file from upstream agent output."""
        if data_folder_path:
            path = Path(data_folder_path) / filename
        else:
            path = get_output_dir(agent_name, workbook_name, self.settings) / filename

        if not path.exists():
            raise FileNotFoundError(f"Required input not found: {path}")

        self.logger.info("Loading %s", path.name)
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_functional_doc(
        self,
        workbook_name: str,
        data_folder_path: str | None,
    ) -> dict:
        """Load functional documentation JSON (required).

        The functional documentation provides critical business context
        that the TDD agent needs to make informed design decisions.
        Raises ``FileNotFoundError`` if the functional doc is not available.
        """
        return self._load_json(
            workbook_name,
            FUNCTIONAL_DOC_JSON,
            "tableau_functional_doc_agent",
            data_folder_path,
        )

    # ── Assessment merging ─────────────────────────────────────────────

    @staticmethod
    def _merge_assessment(
        call1_assessment: MigrationAssessment,
        report: ReportDesign,
    ) -> MigrationAssessment:
        """Merge assessment from Call 1 with any report-level issues.

        The complexity score comes from Call 1; report-specific issues
        are added to the manual_items list.
        """
        manual_items = list(call1_assessment.manual_items)

        # Flag pages with many visuals as potentially complex
        for page in report.pages:
            if len(page.visuals) > 8:
                manual_items.append(f"Page '{page.display_name}' has " f"{len(page.visuals)} visuals — review layout")

        return MigrationAssessment(
            complexity_score=call1_assessment.complexity_score,
            summary=call1_assessment.summary,
            warnings=list(call1_assessment.warnings),
            manual_items=manual_items,
        )

    # ── Output saving ──────────────────────────────────────────────────

    def _save_outputs(
        self,
        workbook_name: str,
        tdd: TargetTechnicalDocumentation,
        *,
        reset_output: bool = True,
    ) -> Path:
        """Save all TDD output files to the agent's output directory."""
        output_dir = get_output_dir(
            self.skill_name,
            workbook_name,
            self.settings,
        )
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        # Section JSONs
        self._write_json(
            output_dir / SEMANTIC_MODEL_DESIGN_FILE,
            tdd.semantic_model.model_dump(mode="json"),
        )
        self._write_json(
            output_dir / DAX_MEASURES_DESIGN_FILE,
            tdd.dax_measures.model_dump(mode="json"),
        )
        self._write_json(
            output_dir / REPORT_DESIGN_FILE,
            tdd.report.model_dump(mode="json"),
        )
        self._write_json(
            output_dir / MIGRATION_ASSESSMENT_FILE,
            tdd.assessment.model_dump(mode="json"),
        )

        # Human-readable renderings
        md_content = render_markdown(tdd)
        html_content = render_html(tdd)
        (output_dir / MD_FILENAME).write_text(
            md_content,
            encoding="utf-8",
        )
        (output_dir / HTML_FILENAME).write_text(
            html_content,
            encoding="utf-8",
        )

        self.logger.info(
            "Output: %s/%s",
            self.skill_name,
            workbook_name,
        )
        return output_dir

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        """Write a dict to a JSON file with pretty formatting."""
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
