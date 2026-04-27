"""TableDecision — one Power BI table (regular or calculation group)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from Tableau2PowerBI.agents.semantic_model.models.column_decision import ColumnDecision


class TableDecision(BaseModel):
    """One Power BI table (regular or calculation group).

    Regular tables have columns and an M query; calculation group tables
    have ``is_calc_group=True`` and a list of ``calc_items`` instead.
    """

    name: str  # TMDL declaration name and .tmdl filename
    query_group: Literal["Fact", "Dimension"]  # PBI query group classification
    columns: list[ColumnDecision]  # Empty for calc groups
    m_query: str = ""  # Full Power Query M expression (let/in)
    is_calc_group: bool = False  # True for calculation group tables
    calc_items: list[str] = Field(default_factory=list)  # Calc item names (calc groups only)
