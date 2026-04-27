"""TmdlMeasuresDecisions — validated contract for the DAX measures generator output."""

from __future__ import annotations

from pydantic import BaseModel, Field

from Tableau2PowerBI.core.models import MigrationWarning


class TmdlMeasuresDecisions(BaseModel):
    """Validated contract for the DAX measures generator output.

    The LLM must return a non-empty TMDL string.  Warnings are
    normalised by :func:`normalise_warnings` before validation.
    """

    measures_tmdl: str = Field(min_length=1)
    warnings: list[MigrationWarning] = Field(default_factory=list)
