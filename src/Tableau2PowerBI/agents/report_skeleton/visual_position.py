"""VisualPosition — position and size of a visual on a Power BI page."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisualPosition(BaseModel):
    """Position and size of a visual on a Power BI page."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    tab_order: int = Field(ge=0)
