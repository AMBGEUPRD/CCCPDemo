"""Stage 3 — PBIP Semantic Model Generator Agent.

This is the **LLM-powered** stage of the pipeline.  It reads the
``semantic_model_input.json`` produced by Stage 1 and asks the model to
return structured *decisions* (tables, columns, M queries, relationships,
parameters, warnings) as a JSON object validated by the Pydantic models
in :mod:`.models`.

The validated decisions are then passed to the deterministic
:class:`~.assembler.SemanticModelAssembler`, which renders the TMDL
and JSON files for the ``.SemanticModel/`` folder.

Retry-with-feedback: If validation fails, the error details are
injected back into the prompt and the model is asked to fix its output.
The maximum number of retries is controlled by ``MAX_VALIDATION_RETRIES``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import ValidationError

from Tableau2PowerBI.agents.semantic_model.assembler import (
    SemanticModelAssembler,
)
from Tableau2PowerBI.agents.semantic_model.models import (
    SemanticModelDecisions,
    WarningDecision,
)
from Tableau2PowerBI.core.agent import Agent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.json_response import parse_llm_json_object
from Tableau2PowerBI.core.prompt_utils import compact_json
from Tableau2PowerBI.core.output_dirs import (
    ensure_output_dir,
    get_output_dir,
    reset_output_dir,
    resolve_safe_path,
    validate_name,
)

logger = logging.getLogger(__name__)

# Prefix prepended to every prompt sent to the LLM.
# The {semantic_model_name} placeholder is filled at runtime.
PROMPT_PREFIX = (
    "Analyze the Target Technical Design (TDD) below and return structured decisions "
    "for building a Power BI semantic model.\n"
    "Use the semantic model name '{semantic_model_name}' for all table references.\n\n"
)

# Filename for the migration warnings JSON written alongside the TMDL output.
WARNINGS_FILE_NAME = "migration_warnings.json"

# Characters illegal in TMDL identifiers and Windows filenames.
_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize_table_name(name: str) -> str:
    """Sanitize a name for use as a TMDL identifier and ``.tmdl`` filename."""
    return _ILLEGAL_FILENAME_CHARS.sub("_", name.strip())


def _resolve_pbi_table_names(metadata: dict) -> list[dict]:
    """Pre-compute deterministic PBI table names from Tableau metadata.

    Naming rules:

    * Single-table datasource → use ``datasource.name``
    * Multi-table datasource  → use ``table.name`` (sheet/physical table name)
    * All names sanitized (illegal filename chars replaced with ``_``)
    * Duplicates resolved with ``_2``, ``_3``, … suffixes

    Returns a list of dicts, one per expected PBI table, each containing:

    * ``datasource_name`` – original Tableau datasource name
    * ``table_index`` – index within the datasource's ``tables[]``
    * ``original_table_name`` – the sheet/table name from metadata
    * ``pbi_table_name`` – the final deterministic PBI table name
    * ``source_columns`` – set of physical column names (for enforcement matching)
    """
    entries: list[dict] = []
    for ds in metadata.get("datasources", []):
        ds_name = ds.get("name", "UnknownDatasource")
        tables = ds.get("tables", [])
        for i, table in enumerate(tables):
            base = ds_name if len(tables) == 1 else table.get("name", f"Table_{i}")
            col_names = {c.get("name", "") for c in table.get("columns", [])}
            entries.append(
                {
                    "datasource_name": ds_name,
                    "table_index": i,
                    "original_table_name": table.get("name", ""),
                    "raw_name": base,
                    "source_columns": col_names,
                }
            )

    # Deduplicate sanitized names with _2, _3, … suffixes.
    seen: dict[str, int] = {}
    for entry in entries:
        sanitized = _sanitize_table_name(entry["raw_name"])
        if sanitized in seen:
            seen[sanitized] += 1
            entry["pbi_table_name"] = f"{sanitized}_{seen[sanitized]}"
        else:
            seen[sanitized] = 1
            entry["pbi_table_name"] = sanitized

    return entries


def _enforce_table_names(
    decisions: SemanticModelDecisions,
    table_name_entries: list[dict],
) -> None:
    """Enforce pre-computed table names on LLM output.  Modifies *decisions* in-place.

    If the LLM returned names that don't match the expected set, this
    function builds a rename mapping (using column overlap as a heuristic)
    and applies it to all table names and relationship references.
    """
    expected_names = {e["pbi_table_name"] for e in table_name_entries}
    actual_names = {t.name for t in decisions.tables}

    if actual_names == expected_names:
        return  # Names already match — nothing to do.

    logger.info(
        "Table names mismatch — enforcing pre-computed names. Expected: %s, Got: %s",
        sorted(expected_names),
        sorted(actual_names),
    )

    rename_map: dict[str, str] = {}
    used: set[str] = set()

    # Pass 1: exact matches
    for table in decisions.tables:
        if table.name in expected_names:
            used.add(table.name)

    # Pass 2: match remaining tables by source-column overlap
    for table in decisions.tables:
        if table.name in used:
            continue
        table_cols = {c.source_column for c in table.columns}
        best_match: str | None = None
        best_overlap = 0
        for entry in table_name_entries:
            exp_name = entry["pbi_table_name"]
            if exp_name in used:
                continue
            overlap = len(table_cols & entry["source_columns"])
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = exp_name
        if best_match:
            rename_map[table.name] = best_match
            used.add(best_match)
        else:
            logger.warning("Could not match LLM table '%s' to any expected name.", table.name)

    if not rename_map:
        return

    logger.info("Renaming tables: %s", rename_map)
    for table in decisions.tables:
        if table.name in rename_map:
            table.name = rename_map[table.name]
    for rel in decisions.relationships:
        if rel.from_table in rename_map:
            rel.from_table = rename_map[rel.from_table]
        if rel.to_table in rename_map:
            rel.to_table = rename_map[rel.to_table]


class PBIPSemanticModelGeneratorAgent(Agent):
    """LLM-driven semantic model generator.

    Reads Tableau metadata, sends it to the LLM with the SKILL.md prompt,
    validates the response with Pydantic, and writes TMDL files via the
    deterministic assembler.
    """

    def __init__(self, model: str | None = None, settings: AgentSettings | None = None):
        super().__init__(
            skill_name="pbip_semantic_model_generator_agent",
            model=model,
            settings=settings,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def generate_pbip_semantic_model(
        self,
        workbook_name: str,
        semantic_model_name: str | None = None,
        *,
        reset_output: bool = True,
    ) -> None:
        """Run the full generation pipeline: read TDD → LLM → validate → assemble.

        Reads the Target Technical Documentation (TDD) as the single source
        of truth for table design, column definitions, relationships, and
        M query strategies.  The raw Tableau metadata is no longer consumed
        directly — the TDD agent has already distilled it.

        Args:
            workbook_name: Identifies the TDD output to read from.
            semantic_model_name: Name used in TMDL declarations; defaults to *workbook_name*.
        """
        workbook_name = validate_name("Workbook name", workbook_name)
        semantic_model_name = validate_name(
            "Semantic model name",
            semantic_model_name or workbook_name,
        )
        # Clean output directory so stale files from previous runs never survive
        output_dir = get_output_dir(self.skill_name, workbook_name, self.settings)
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        # Load TDD — the single source of design truth
        tdd_sm, tdd_dax = self._load_tdd(workbook_name)

        # Pre-computed table names come from TDD (already deterministic)
        table_name_entries = [
            {
                "datasource_name": t.get("source_datasource", ""),
                "table_index": i,
                "original_table_name": t.get("source_table", ""),
                "pbi_table_name": t["name"],
                "source_columns": {c["source_column"] for c in t.get("columns", [])},
            }
            for i, t in enumerate(tdd_sm.get("tables", []))
        ]
        self.logger.info(
            "TDD table names: %s",
            [e["pbi_table_name"] for e in table_name_entries],
        )

        prompt = self._build_prompt(tdd_sm, tdd_dax, semantic_model_name, table_name_entries)
        decisions = self._run_with_validation(prompt)

        # Safety net: enforce the pre-computed names even if the LLM deviated.
        _enforce_table_names(decisions, table_name_entries)

        self.logger.info("Agent decisions received and validated.")
        self._save_decisions(decisions, workbook_name, semantic_model_name)
        self.logger.info("PBIP semantic model generation complete.")

    async def generate_pbip_semantic_model_async(
        self,
        workbook_name: str,
        semantic_model_name: str | None = None,
        *,
        reset_output: bool = True,
    ) -> None:
        """Async version of :meth:`generate_pbip_semantic_model`."""
        workbook_name = validate_name("Workbook name", workbook_name)
        semantic_model_name = validate_name(
            "Semantic model name",
            semantic_model_name or workbook_name,
        )
        output_dir = get_output_dir(self.skill_name, workbook_name, self.settings)
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        tdd_sm, tdd_dax = self._load_tdd(workbook_name)
        table_name_entries = [
            {
                "datasource_name": t.get("source_datasource", ""),
                "table_index": i,
                "original_table_name": t.get("source_table", ""),
                "pbi_table_name": t["name"],
                "source_columns": {c["source_column"] for c in t.get("columns", [])},
            }
            for i, t in enumerate(tdd_sm.get("tables", []))
        ]
        self.logger.info(
            "TDD table names: %s",
            [e["pbi_table_name"] for e in table_name_entries],
        )

        prompt = self._build_prompt(tdd_sm, tdd_dax, semantic_model_name, table_name_entries)
        decisions = await self._run_with_validation_async(prompt)

        _enforce_table_names(decisions, table_name_entries)
        self.logger.info("Agent decisions received and validated.")
        self._save_decisions(decisions, workbook_name, semantic_model_name)
        self.logger.info("PBIP semantic model generation complete.")

    # ------------------------------------------------------------------
    # Input reading & prompt building
    # ------------------------------------------------------------------

    def _load_tdd(self, workbook_name: str) -> tuple[dict, dict]:
        """Load TDD semantic_model and dax_measures design sections.

        Returns:
            Tuple of (semantic_model_design dict, dax_measures_design dict).

        Raises:
            FileNotFoundError: If TDD output is missing.
        """
        tdd_dir = get_output_dir(
            "target_technical_doc_agent",
            workbook_name,
            self.settings,
        )
        sm_path = tdd_dir / "semantic_model_design.json"
        dax_path = tdd_dir / "dax_measures_design.json"
        if not sm_path.exists():
            raise FileNotFoundError(
                f"TDD semantic model design not found: {sm_path}. " "Run the target technical doc agent first."
            )
        self.logger.info("Loading TDD from %s", tdd_dir.name)
        tdd_sm = json.loads(sm_path.read_text(encoding="utf-8"))
        tdd_dax: dict = {}
        if dax_path.exists():
            tdd_dax = json.loads(dax_path.read_text(encoding="utf-8"))
        return tdd_sm, tdd_dax

    def read_semantic_model_input(self, workbook_name: str) -> str:
        """Read semantic_model_input.json (legacy — kept for backward compat)."""
        input_path = (
            get_output_dir("tableau_metadata_extractor_agent", workbook_name, self.settings)
            / "semantic_model_input.json"
        )
        if not input_path.exists():
            raise FileNotFoundError(f"Semantic model input not found at: {input_path.resolve()}")
        return input_path.read_text(encoding="utf-8")

    @staticmethod
    def _build_prompt(
        tdd_sm: dict,
        tdd_dax: dict,
        semantic_model_name: str,
        table_name_entries: list[dict] | None = None,
    ) -> str:
        """Build the prompt from TDD design sections.

        Injects the full TDD semantic model design plus a slim summary
        of DAX measures (count + owner tables) for cross-reference.
        """
        header = PROMPT_PREFIX.format(semantic_model_name=semantic_model_name)

        if table_name_entries:
            header += (
                "## Pre-computed Table Names (MANDATORY)\n"
                "The following PBI table names have been pre-computed and MUST be used EXACTLY.\n"
                "Do NOT invent, rename, translate, prefix, or modify table names in any way.\n\n"
            )
            for entry in table_name_entries:
                header += (
                    f'- Datasource "{entry["datasource_name"]}" '
                    f'table "{entry["original_table_name"]}" '
                    f'→ pbi_table_name: "{entry["pbi_table_name"]}"\n'
                )
            header += "\n"

        # Inject the full TDD semantic model design as the primary input
        parts: list[str] = [header]
        parts.append("## Target Technical Design — Semantic Model\n")
        parts.append(compact_json(tdd_sm))
        parts.append("\n\n")

        # Slim DAX measures summary for cross-reference
        measures = tdd_dax.get("measures", [])
        if measures:
            parts.append("## DAX Measures Summary (for cross-reference)\n")
            parts.append(f"Total measures: {len(measures)}\n")
            owner_tables: dict[str, list[str]] = {}
            for m in measures:
                owner_tables.setdefault(m.get("owner_table", "?"), []).append(
                    m.get("caption", m.get("tableau_name", "?"))
                )
            for table, names in sorted(owner_tables.items()):
                parts.append(f"  - {table}: {', '.join(names)}\n")
            parts.append("\n")

        return "".join(parts)

    # ------------------------------------------------------------------
    # LLM call with Pydantic validation and retry-with-feedback
    # ------------------------------------------------------------------

    def _run_with_validation(self, prompt: str) -> SemanticModelDecisions:
        """Call the LLM and validate the response with retry feedback."""
        return self.run_with_validation(
            prompt,
            self._parse_decisions,
            label="Semantic model response",
            parse_exceptions=(ValidationError, ValueError),
        )

    async def _run_with_validation_async(self, prompt: str) -> SemanticModelDecisions:
        """Async version of :meth:`_run_with_validation`."""
        return await self.run_with_validation_async(
            prompt,
            self._parse_decisions,
            label="Semantic model response",
            parse_exceptions=(ValidationError, ValueError),
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @classmethod
    def _parse_decisions(cls, response: str) -> SemanticModelDecisions:
        """Parse and validate the raw LLM response into decisions."""
        raw = parse_llm_json_object(response, logger=logger, enable_recovery=False)
        return SemanticModelDecisions.model_validate(raw)

    # ------------------------------------------------------------------
    # Assembly and file writing
    # ------------------------------------------------------------------

    def save_pbip_semantic_model(
        self,
        response: str,
        workbook_name: str,
        semantic_model_name: str | None = None,
    ) -> None:
        """Parse an LLM decisions response, assemble files, and write to disk."""
        semantic_model_name = validate_name(
            "Semantic model name",
            semantic_model_name or workbook_name,
        )
        decisions = self._parse_decisions(response)
        self._save_decisions(decisions, workbook_name, semantic_model_name)

    def _save_decisions(
        self,
        decisions: SemanticModelDecisions,
        workbook_name: str,
        semantic_model_name: str,
    ) -> None:
        """Assemble the validated decisions into TMDL files and write to disk."""
        assembler = SemanticModelAssembler(decisions, semantic_model_name)
        files = assembler.assemble()
        self._log_warnings(decisions.warnings)
        self._write_output_files(files, workbook_name)
        self._write_warnings_file(decisions.warnings, workbook_name)

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _write_output_files(
        self,
        files: dict[str, str],
        workbook_name: str,
        base_path: Path | None = None,
    ) -> None:
        """Write assembled files to the output directory.

        TMDL files are normalised to CRLF line endings (mandatory for Power BI)
        and written via ``write_bytes()`` to prevent Python's universal newline
        handling from corrupting them on Windows.
        """
        output_root = base_path or get_output_dir(self.skill_name, workbook_name, self.settings)
        output_root.mkdir(parents=True, exist_ok=True)

        for file_path, content in files.items():
            output_file = resolve_safe_path(output_root, file_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # TMDL files require CRLF line endings — enforce this deterministically.
            if file_path.endswith(".tmdl"):
                normalised = content.replace("\r\n", "\n").replace("\n", "\r\n")
            else:
                normalised = content

            output_file.write_bytes(normalised.encode("utf-8"))

        self.logger.info(
            "Wrote %d files to %s",
            len(files),
            output_root.name,
        )

    # ------------------------------------------------------------------
    # Warnings
    # ------------------------------------------------------------------

    def _log_warnings(self, warnings: list[WarningDecision]) -> None:
        if not warnings:
            return
        self.logger.warning("Agent emitted %d migration warning(s):", len(warnings))
        for w in warnings:
            self.logger.warning("  [%s] %s - %s", w.severity.upper(), w.code, w.message)

    def _write_warnings_file(
        self,
        warnings: list[WarningDecision],
        workbook_name: str,
        base_path: Path | None = None,
    ) -> None:
        output_root = base_path or get_output_dir(self.skill_name, workbook_name, self.settings)
        output_root.mkdir(parents=True, exist_ok=True)
        warnings_file = output_root / WARNINGS_FILE_NAME
        data = [w.model_dump() for w in warnings]
        warnings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.logger.info("Saved: %s", warnings_file)
