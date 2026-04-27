"""SkeletonVisual — a single visual slot in the report skeleton manifest."""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

from Tableau2PowerBI.agents.report_skeleton.visual_position import VisualPosition

_HEX_ID_RE = re.compile(r"^[0-9a-f]{20}$")


class SkeletonVisual(BaseModel):
    """A single visual slot in the skeleton manifest.

    Each entry maps a Tableau worksheet to a Power BI visual with
    a predetermined type, hex folder ID, and pixel position.
    """

    worksheet_name: str
    visual_type: str
    hex_id: str
    position: VisualPosition

    @field_validator("hex_id")
    @classmethod
    def validate_hex_id(cls, v: str) -> str:
        """Hex ID must be exactly 20 lowercase hex characters."""
        if not _HEX_ID_RE.match(v):
            raise ValueError(f"hex_id must be 20 lowercase hex chars, got: {v!r}")
        return v

    @field_validator("visual_type")
    @classmethod
    def validate_visual_type(cls, v: str) -> str:
        """Visual type must be a non-empty string."""
        if not v or not v.strip():
            raise ValueError("visual_type must be a non-empty string")
        return v
