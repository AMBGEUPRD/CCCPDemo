"""Functional Documentation Agent — workbook analysis and documentation.

Analyzes extracted Tableau metadata and produces a hierarchical functional
documentation describing what the workbook does from a business perspective:
dashboards, worksheets, data sources, parameters, and calculated fields.

Output is rendered in two formats:
- **Markdown** — flat, portable, version-control friendly
- **HTML** — self-contained, navigable with collapsible sections and sidebar TOC

Typical usage::

    from Tableau2PowerBI.agents.functional_doc import FunctionalDocAgent

    with FunctionalDocAgent() as agent:
        agent.create()
        md_path, html_path = agent.generate_documentation("Supermercato")
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from Tableau2PowerBI.agents.metadata_extractor.downstream_payloads import (
    FUNCTIONAL_DOC_INPUT_SLIM_FILENAME,
    build_functional_doc_input_slim,
)
from Tableau2PowerBI.agents.functional_doc.models import FunctionalDocumentation
from Tableau2PowerBI.agents.functional_doc.renderer import (
    render_html,
    render_markdown,
)
from Tableau2PowerBI.core.agent import Agent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.prompt_utils import compact_json
from Tableau2PowerBI.core.output_dirs import ensure_output_dir, get_output_dir, reset_output_dir
from Tableau2PowerBI.core.llm_output_parsing import strip_markdown_fences

# Prefix prepended to every prompt sent to the LLM.
PROMPT_PREFIX = (
    "Analyze the following Tableau workbook metadata and return a structured "
    "JSON documenting the workbook's functional purpose from a business perspective.\n"
    "Describe what each dashboard, worksheet, data source, parameter, and "
    "calculated field does — focus on the *business meaning*, not the technical "
    "implementation.\n\n"
)

# Output filenames written to the agent's output directory.
MD_FILENAME = "functional_documentation.md"
HTML_FILENAME = "functional_documentation.html"
JSON_FILENAME = "functional_documentation.json"


class FunctionalDocAgent(Agent):
    """LLM-powered agent that produces functional documentation of a Tableau workbook.

    Reads the ``tableau_metadata.json`` from Stage 1 output and asks the LLM to
    return a structured JSON analysing every dashboard, worksheet, data source,
    parameter, and calculated field from a business perspective.

    The structured JSON is then passed to deterministic renderers that produce
    Markdown and self-contained HTML files.
    """

    def __init__(
        self,
        model: str | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        super().__init__(
            skill_name="tableau_functional_doc_agent",
            model=model,
            settings=settings,
        )

    # ── Public API ─────────────────────────────────────────────────────

    def generate_documentation(
        self,
        workbook_name: str,
        data_folder_path: str | None = None,
        *,
        reset_output: bool = True,
    ) -> tuple[Path, Path]:
        """Generate functional documentation for a Tableau workbook.

        Args:
            workbook_name: Stem of the workbook file (no extension).
            data_folder_path: Optional path to a folder containing
                ``tableau_metadata.json``.  When *None*, the file is read
                from the metadata extractor's default output directory.

        Returns:
            A ``(markdown_path, html_path)`` tuple pointing to the two
            generated documentation files.
        """
        self.logger.info("Generating functional documentation for '%s'", workbook_name)

        # ── Load metadata ──────────────────────────────────────────────
        metadata = self._load_metadata(workbook_name, data_folder_path)

        # ── Call LLM ───────────────────────────────────────────────────
        prompt = self._build_prompt(metadata)
        doc = self.run_with_validation(
            prompt,
            self._parse_response,
            label="Functional documentation response",
            parse_exceptions=(ValidationError, ValueError),
        )

        # ── Render outputs ─────────────────────────────────────────────
        output_dir = get_output_dir(
            self.skill_name,
            workbook_name,
            self.settings,
        )
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        md_path = output_dir / MD_FILENAME
        html_path = output_dir / HTML_FILENAME
        json_path = output_dir / JSON_FILENAME

        md_content = render_markdown(doc)
        html_content = render_html(doc)
        json_content = doc.model_dump_json(indent=2)

        md_path.write_text(md_content, encoding="utf-8")
        html_path.write_text(html_content, encoding="utf-8")
        json_path.write_text(json_content, encoding="utf-8")

        self.logger.info("Markdown: %s", md_path.name)
        self.logger.info("HTML:     %s", html_path.name)
        self.logger.info("JSON:     %s", json_path.name)
        self.logger.info("Output dir: %s", output_dir)
        return md_path, html_path

    async def generate_documentation_async(
        self,
        workbook_name: str,
        data_folder_path: str | None = None,
        *,
        reset_output: bool = True,
    ) -> tuple[Path, Path]:
        """Async version of :meth:`generate_documentation`."""
        self.logger.info("Generating functional documentation for '%s'", workbook_name)

        metadata = self._load_metadata(workbook_name, data_folder_path)
        prompt = self._build_prompt(metadata)
        doc = await self.run_with_validation_async(
            prompt,
            self._parse_response,
            label="Functional documentation response",
            parse_exceptions=(ValidationError, ValueError),
        )

        output_dir = get_output_dir(self.skill_name, workbook_name, self.settings)
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        md_path = output_dir / MD_FILENAME
        html_path = output_dir / HTML_FILENAME
        json_path = output_dir / JSON_FILENAME

        md_path.write_text(render_markdown(doc), encoding="utf-8")
        html_path.write_text(render_html(doc), encoding="utf-8")
        json_path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")

        self.logger.info("Output dir: %s", output_dir)
        return md_path, html_path

    # ── Private helpers ────────────────────────────────────────────────

    def _load_metadata(
        self,
        workbook_name: str,
        data_folder_path: str | None,
    ) -> dict:
        """Load the best available metadata payload for functional docs.

        Uses full metadata when it is below the configured threshold and
        switches to the slimmed functional-doc payload when it is above.
        If the slimmed file is missing, it is regenerated from the full
        metadata using the canonical builder from the extractor module.
        """
        extractor_dir = self._get_metadata_dir(workbook_name, data_folder_path)
        full_path = extractor_dir / "tableau_metadata.json"
        slim_path = extractor_dir / FUNCTIONAL_DOC_INPUT_SLIM_FILENAME

        if not full_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {full_path}")

        threshold_kb = self.settings.functional_doc_input_threshold_kb
        full_size_kb = full_path.stat().st_size / 1024
        self.logger.info("Functional doc full input size: %.1f KB", full_size_kb)

        if full_size_kb <= threshold_kb:
            self.logger.info("Functional doc input source: full")
            raw = full_path.read_text(encoding="utf-8")
            return json.loads(raw)

        if not slim_path.exists():
            self.logger.warning(
                "Slim functional doc input missing for '%s'; regenerating.",
                workbook_name,
            )
            full_metadata = json.loads(full_path.read_text(encoding="utf-8"))
            slim_metadata = build_functional_doc_input_slim(full_metadata)
            slim_path.write_text(
                json.dumps(slim_metadata, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        selected_size_kb = slim_path.stat().st_size / 1024
        self.logger.info("Functional doc input source: slim")
        self.logger.info("Functional doc selected input size: %.1f KB", selected_size_kb)
        if selected_size_kb > threshold_kb:
            self.logger.warning(
                "Slim functional doc input is still large (%.1f KB > %d KB); continuing.",
                selected_size_kb,
                threshold_kb,
            )

        raw = slim_path.read_text(encoding="utf-8")
        return json.loads(raw)

    def _get_metadata_dir(self, workbook_name: str, data_folder_path: str | None) -> Path:
        """Resolve the folder containing extracted metadata files."""
        if data_folder_path:
            return Path(data_folder_path)
        return get_output_dir(
            "tableau_metadata_extractor_agent",
            workbook_name,
            self.settings,
        )

    def _build_prompt(self, metadata: dict) -> str:
        """Assemble the prompt: instruction header + compact metadata JSON."""
        return PROMPT_PREFIX + compact_json(metadata)

    def _parse_response(self, raw_response: str) -> FunctionalDocumentation:
        """Parse and validate the LLM response into a typed model."""
        clean = strip_markdown_fences(raw_response)
        try:
            data = json.loads(clean)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM response is not valid JSON. " f"First 300 chars: {raw_response[:300]!r}") from exc
        return FunctionalDocumentation.model_validate(data)

    async def _parse_response_async(self, raw_response: str) -> FunctionalDocumentation:
        """Async version of :meth:`_parse_response`."""
        return self._parse_response(raw_response)
