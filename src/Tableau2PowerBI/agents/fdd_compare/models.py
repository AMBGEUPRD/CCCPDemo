"""Pydantic output models for the FDD comparison agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DimensionalScores(BaseModel):
    """Per-dimension similarity scores for a report pair (all 0.0–1.0)."""

    business_scope: float = Field(ge=0.0, le=1.0)
    data_model: float = Field(ge=0.0, le=1.0)
    measures_kpis: float = Field(ge=0.0, le=1.0)
    visual_structure: float = Field(ge=0.0, le=1.0)
    target_audience: float = Field(ge=0.0, le=1.0)
    overall: float = Field(ge=0.0, le=1.0)


class SimilarityPair(BaseModel):
    """Per-dimension similarity scores between two reports."""

    report_a: str
    report_b: str
    scores: DimensionalScores
    reason: str


class ReportGroup(BaseModel):
    """A cluster of reports with a consolidation verdict."""

    verdict: Literal["merge", "keep_separate", "borderline"]
    reports: list[str]
    shared: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    merge_action: str = ""
    reason: str


class KpiEntry(BaseModel):
    """A single business KPI found across the portfolio."""

    name: str
    description: str
    reports: list[str]  # report names that expose this KPI


class RationalizationScore(BaseModel):
    """Business value / usage scores and quadrant placement for one report."""

    report: str
    value: float = Field(ge=0.0, le=1.0)   # business value inferred from FDD
    usage: float = Field(ge=0.0, le=1.0)   # estimated adoption (simulated)
    quadrant: Literal["keep", "merge", "retire", "add"]
    rationale: str
    early_value: bool = False  # True when value >= 0.75 and usage >= 0.75


class ComparisonResult(BaseModel):
    """Full output of the FDD comparison agent."""

    executive_summary: str
    profiles: dict[str, str] = Field(default_factory=dict)
    similarity_pairs: list[SimilarityPair] = Field(default_factory=list)
    groups: list[ReportGroup] = Field(default_factory=list)
    narrative: str = ""
    kpi_glossary: list[KpiEntry] = Field(default_factory=list)
    rationalization: list[RationalizationScore] = Field(default_factory=list)
