"""FDD Comparison Agent — compares Functional Design Documentation across multiple reports."""

from __future__ import annotations

import json
import re
from pathlib import Path

from Tableau2PowerBI.core.agent.base import Agent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.agents.fdd_compare.models import ComparisonResult

_SKILL_DIR = Path(__file__).parent


class FDDCompareAgent(Agent):
    """Compares FDD documents for N reports and produces a structured consolidation recommendation.

    Uses a custom skill_loader to read SKILL.md from its own directory,
    bypassing _SKILL_FOLDER_MAP in core/agent/base.py — no core changes needed.
    """

    _SKILL_NAME = "fdd_compare_agent"

    def __init__(
        self,
        model: str | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        super().__init__(
            self._SKILL_NAME,
            model=model,
            settings=settings,
            skill_loader=lambda _: (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"),
        )

    def compare(self, fdd_docs: dict[str, str]) -> ComparisonResult:
        """Compare FDD documents and return a structured result.

        Args:
            fdd_docs: Mapping of workbook_name → FDD markdown text.

        Returns:
            ComparisonResult with similarity matrix, groups, and narrative.
        """
        if len(fdd_docs) < 2:
            raise ValueError("At least 2 FDD documents are required for comparison")
        prompt = self._build_prompt(fdd_docs)
        return self.run_with_validation(
            prompt,
            parser=self._parse_response,
            label="fdd_comparison",
        )

    def _build_prompt(self, fdd_docs: dict[str, str]) -> str:
        """Concatenate FDDs with clear section separators for the LLM."""
        parts = [f"## Report: {name}\n\n{md}" for name, md in fdd_docs.items()]
        return "\n\n---\n\n".join(parts)

    def _parse_response(self, raw: str) -> ComparisonResult:
        """Strip markdown fences, parse JSON, validate against ComparisonResult schema."""
        # Strip optional ```json ... ``` fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
        data = json.loads(cleaned)
        return ComparisonResult.model_validate(data)
