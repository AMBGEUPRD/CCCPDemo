"""TmdlMeasuresGeneratorAgent — translate Tableau calculated fields to Power BI DAX measures."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from Tableau2PowerBI.agents.dax_measures.tmdl_measures_decisions import TmdlMeasuresDecisions
from Tableau2PowerBI.core.agent import Agent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.json_response import parse_llm_json_object
from Tableau2PowerBI.core.prompt_utils import compact_json
from Tableau2PowerBI.core.output_dirs import ensure_output_dir, get_output_dir, reset_output_dir
from Tableau2PowerBI.core.llm_output_parsing import normalise_warnings

logger = logging.getLogger(__name__)

_TMDL_FILE_NAME = "measures.tmdl"
_WARNINGS_FILE_NAME = "warnings.json"


def parse_decisions_response(response: str) -> TmdlMeasuresDecisions:
    """Parse, normalise, and validate the raw LLM response."""
    raw = parse_llm_json_object(response, logger=logger, enable_recovery=True)
    measures_content = TmdlMeasuresGeneratorAgent._normalise_tmdl(raw.get("measures.tmdl", ""))
    warnings = normalise_warnings(raw.get("_warnings", []))
    return TmdlMeasuresDecisions.model_validate({"measures_tmdl": measures_content, "warnings": warnings})


class TmdlMeasuresGeneratorAgent(Agent):
    """Translate Tableau calculated fields into Power BI DAX measures.

    Sends Tableau metadata to the LLM, validates the response with
    Pydantic, retries with error feedback on validation failure, and
    writes the resulting ``measures.tmdl`` to disk.
    """

    def __init__(
        self,
        model: str | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        super().__init__(
            skill_name="tmdl_measures_generator_agent",
            model=model,
            settings=settings,
        )
        self.prompt_template = (
            "Parse this Tableau workbook metadata JSON and migrate all calculated "
            "fields, measures, and parameters to a valid Power BI TMDL measures file "
            "following the skill instructions precisely.\n\n"
            "Return a JSON object with exactly two keys:\n"
            '  "measures.tmdl" : the full TMDL text as a single string\n'
            '  "_warnings"     : a list of { "severity", "code", "message" } objects '
            "for every measure that could not be translated automatically "
            "(table calculations, circular references, etc.).\n\n"
            "Do NOT wrap the response in markdown fences.\n\n"
            "Return the measures.tmdl in a valid structure to be imported in PowerBi. "
            "Avoid comments.\n\n"
        )

    def generate_tmdl_measures(self, workbook_name: str, *, reset_output: bool = True) -> None:
        """Full pipeline: read TDD → LLM → validate → save."""
        tdd_dax, tdd_sm = self._load_tdd(workbook_name)
        prompt = self._build_prompt(tdd_dax, tdd_sm)
        decisions = self._run_with_validation(prompt)
        self.logger.info("Agent decisions received and validated.")

        output_dir = get_output_dir(self.skill_name, workbook_name, self.settings)
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        self._save_decisions(decisions, output_dir)
        self.logger.info("TMDL measures generation complete.")

    async def generate_tmdl_measures_async(self, workbook_name: str, *, reset_output: bool = True) -> None:
        """Async version of :meth:`generate_tmdl_measures`."""
        tdd_dax, tdd_sm = self._load_tdd(workbook_name)
        prompt = self._build_prompt(tdd_dax, tdd_sm)
        decisions = await self._run_with_validation_async(prompt)
        self.logger.info("Agent decisions received and validated.")

        output_dir = get_output_dir(self.skill_name, workbook_name, self.settings)
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        self._save_decisions(decisions, output_dir)
        self.logger.info("TMDL measures generation complete.")

    def _load_tdd(self, workbook_name: str) -> tuple[dict, dict]:
        """Load TDD dax_measures and semantic_model design sections."""
        tdd_dir = get_output_dir("target_technical_doc_agent", workbook_name, self.settings)
        dax_path = tdd_dir / "dax_measures_design.json"
        sm_path = tdd_dir / "semantic_model_design.json"
        if not dax_path.exists():
            raise FileNotFoundError(
                f"TDD DAX measures design not found: {dax_path}. " "Run the target technical doc agent first."
            )
        self.logger.info("Loading TDD from %s", tdd_dir.name)
        tdd_dax = json.loads(dax_path.read_text(encoding="utf-8"))
        tdd_sm: dict = {}
        if sm_path.exists():
            tdd_sm = json.loads(sm_path.read_text(encoding="utf-8"))
        return tdd_dax, tdd_sm

    def _build_prompt(self, tdd_dax: dict, tdd_sm: dict) -> str:
        """Compose the prompt from TDD design sections."""
        parts: list[str] = []
        tables = tdd_sm.get("tables", [])
        if tables:
            table_names = [t["name"] for t in tables]
            table_list = "\n".join(f"  - {name}" for name in sorted(table_names))
            parts.append(
                "## Available Power BI Tables (MANDATORY)\n"
                "The semantic model design specifies EXACTLY these table names.\n"
                "You MUST use these names — do NOT invent or rename tables.\n"
                "Map every column reference and measure to one of these tables:\n"
                f"{table_list}\n\n"
            )
        parts.append(self.prompt_template)
        parts.append("## Target Technical Design — DAX Measures\n")
        parts.append(compact_json(tdd_dax))
        parts.append("\n")
        return "".join(parts)

    def _run_with_validation(self, prompt: str) -> TmdlMeasuresDecisions:
        """Call the LLM and validate, retrying on failure."""
        return self.run_with_validation(
            prompt,
            parse_decisions_response,
            label="TMDL measures response",
            parse_exceptions=(ValidationError, ValueError),
        )

    async def _run_with_validation_async(self, prompt: str) -> TmdlMeasuresDecisions:
        """Async version of :meth:`_run_with_validation`."""
        return await self.run_with_validation_async(
            prompt,
            parse_decisions_response,
            label="TMDL measures response",
            parse_exceptions=(ValidationError, ValueError),
        )

    @staticmethod
    def _normalise_tmdl(content) -> str:
        """Coerce the TMDL value into a plain string."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("line") or item.get("content") or json.dumps(item))
                else:
                    parts.append(str(item))
            return "\r\n".join(parts)
        return json.dumps(content, indent=2)

    def _save_decisions(self, decisions: TmdlMeasuresDecisions, output_dir: Path) -> None:
        """Write measures.tmdl and warnings.json from validated decisions."""
        tmdl_path = output_dir / _TMDL_FILE_NAME
        tmdl_path.write_bytes(decisions.measures_tmdl.encode("utf-8"))
        self.logger.info("Saved %s", _TMDL_FILE_NAME)

        if decisions.warnings:
            self.logger.warning("Agent emitted %d migration warning(s):", len(decisions.warnings))
            for w in decisions.warnings:
                self.logger.warning("  [%s] %s — %s", w.severity, w.code, w.message)
        else:
            self.logger.info("No migration warnings emitted.")

        warnings_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "warning_count": len(decisions.warnings),
            "warnings": [w.model_dump() for w in decisions.warnings],
        }
        warnings_path = output_dir / _WARNINGS_FILE_NAME
        warnings_path.write_text(json.dumps(warnings_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.logger.info("Saved %s", _WARNINGS_FILE_NAME)
