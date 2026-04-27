"""PageVisualsOutput — validated output from the page visuals agent."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from Tableau2PowerBI.core.models import MigrationWarning


class PageVisualsOutput(BaseModel):
    """Validated output from the page visuals agent.

    Maps visual hex_id → complete visual.json content string.
    Must contain at least one visual.
    """

    visuals: dict[str, str]
    warnings: list[MigrationWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_has_visuals(self) -> PageVisualsOutput:
        """The response must contain at least one visual entry."""
        if not self.visuals:
            raise ValueError("Response contains no visual entries")
        return self
