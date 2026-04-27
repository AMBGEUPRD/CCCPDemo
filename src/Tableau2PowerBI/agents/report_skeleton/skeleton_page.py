"""SkeletonPage — a page (one per Tableau dashboard) in the skeleton manifest."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from Tableau2PowerBI.agents.report_skeleton.skeleton_visual import SkeletonVisual

_HEX_ID_RE = re.compile(r"^[0-9a-f]{20}$")


class SkeletonPage(BaseModel):
    """A page (one per Tableau dashboard) in the skeleton manifest.

    Contains the dashboard-to-page mapping and the visual slots
    for all worksheets on that dashboard.
    """

    dashboard_name: str
    display_name: str
    hex_id: str
    width: int = 1280
    height: int = Field(ge=1)
    visuals: list[SkeletonVisual]

    @field_validator("hex_id")
    @classmethod
    def validate_hex_id(cls, v: str) -> str:
        """Hex ID must be exactly 20 lowercase hex characters."""
        if not _HEX_ID_RE.match(v):
            raise ValueError(f"hex_id must be 20 lowercase hex chars, got: {v!r}")
        return v
