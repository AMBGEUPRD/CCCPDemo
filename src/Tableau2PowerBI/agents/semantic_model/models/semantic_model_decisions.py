"""SemanticModelDecisions — top-level contract between the LLM and the assembler."""

from __future__ import annotations

from pydantic import BaseModel, Field

from Tableau2PowerBI.agents.semantic_model.models.parameter_decision import ParameterDecision
from Tableau2PowerBI.agents.semantic_model.models.relationship_decision import RelationshipDecision
from Tableau2PowerBI.agents.semantic_model.models.table_decision import TableDecision
from Tableau2PowerBI.agents.semantic_model.models.warning_decision import WarningDecision


class SemanticModelDecisions(BaseModel):
    """Top-level contract between the LLM and the deterministic assembler.

    The LLM returns a JSON object matching this schema.  Any response
    that fails validation is retried with error feedback injected.
    """

    tables: list[TableDecision]
    relationships: list[RelationshipDecision] = Field(default_factory=list)
    parameters: list[ParameterDecision] = Field(default_factory=list)
    warnings: list[WarningDecision] = Field(default_factory=list)
    source_query_culture: str = "en-US"  # BCP-47 locale inferred from workbook content
