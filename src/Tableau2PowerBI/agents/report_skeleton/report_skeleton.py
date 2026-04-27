"""ReportSkeleton — validated contract for the skeleton agent output."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from Tableau2PowerBI.agents.report_skeleton.skeleton_page import SkeletonPage
from Tableau2PowerBI.core.models import MigrationWarning


class ReportSkeleton(BaseModel):
    """Validated contract for the skeleton agent output.

    Contains the page/visual structure for the entire report.
    Must have at least one page.
    """

    pages: list[SkeletonPage]
    warnings: list[MigrationWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_has_pages(self) -> ReportSkeleton:
        """A skeleton must contain at least one page."""
        if not self.pages:
            raise ValueError("Skeleton must contain at least one page")
        return self
