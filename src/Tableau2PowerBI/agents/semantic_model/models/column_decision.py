"""ColumnDecision — a single column in a Power BI table."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ColumnDecision(BaseModel):
    """A single column in a Power BI table.

    ``source_column`` must match the physical column name exactly as it
    appears in the data source (never quoted, never renamed).
    """

    name: str  # Display name (from Tableau caption or logical name)
    source_column: str  # Physical source column (remote_name, never quoted)
    data_type: Literal["string", "int64", "double", "boolean", "dateTime"]
    summarize_by: Literal["none", "sum"] = "none"  # "none" for dimensions, "sum" for measures
