"""Pydantic v2 models for the Target Technical Documentation (TDD) Agent.

Defines the structured contract produced by the TDD agent and consumed
by downstream generation agents (semantic model, DAX measures, report
visuals).  The TDD bridges the gap between the business-level functional
documentation and the technical artefacts — it contains all the design
decisions that generation agents need without requiring them to
re-analyse raw metadata.

The models are split into three focused sections:

- **SemanticModelDesign** — table inventory, columns, relationships,
  M query strategy, parameters
- **DaxMeasuresDesign** — calculated field inventory, translatability
  assessment, target DAX approach, table assignments
- **ReportDesign** — page map, visual inventory with resolved field
  bindings and filter specifications

Plus a cross-cutting **MigrationAssessment** (warnings, complexity
score, manual intervention items).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ════════════════════════════════════════════════════════════════════════
#  Section 1 — Semantic Model Design
# ════════════════════════════════════════════════════════════════════════


class ColumnDesign(BaseModel):
    """Design specification for a single Power BI column.

    Maps a Tableau source column to its Power BI equivalent with
    the correct data type and summarisation strategy.
    """

    name: str  # Display name (from Tableau caption or logical name)
    source_column: str  # Physical source column name (never quoted)
    data_type: Literal["string", "int64", "double", "boolean", "dateTime"]
    summarize_by: Literal["none", "sum"] = "none"
    semantic_role: str = ""
    # Tableau semantic role hint for PBI data categorization.
    # Examples: "City", "State", "Country", "ZipCode", "Latitude", "Longitude".
    # Empty when no role applies.
    description: str = ""  # Business meaning (from functional doc)


class MQueryStrategy(BaseModel):
    """Strategy for generating the Power Query M expression.

    Instead of asking the LLM to write M code from scratch, the TDD
    agent decides the approach and key parameters so the downstream
    semantic model agent can focus on correct syntax.
    """

    connector_type: str  # e.g. "Excel.Workbook", "Sql.Database", "Csv.Document"
    source_expression: str  # e.g. file path pattern or server/database
    navigation_steps: list[str] = Field(default_factory=list)
    # e.g. ["Source{[Name=\"Ordini\"]}[Data]", "Table.TransformColumnTypes(...)"]
    notes: str = ""  # Any special handling required (QuoteStyle, xls vs xlsx, etc.)


class TableDesign(BaseModel):
    """Design specification for a single Power BI table."""

    name: str  # PBI table name (deterministic, pre-computed)
    source_datasource: str  # Original Tableau datasource name
    source_table: str  # Original Tableau table/sheet name
    query_group: Literal["Fact", "Dimension"]
    columns: list[ColumnDesign]
    m_query_strategy: MQueryStrategy
    is_calc_group: bool = False
    calc_items: list[str] = Field(default_factory=list)
    description: str = ""  # Business purpose (from functional doc)


class RelationshipDesign(BaseModel):
    """Design specification for a table relationship."""

    from_table: str  # Fact table (many side)
    from_column: str  # Foreign key column
    to_table: str  # Dimension table (one side)
    to_column: str  # Primary key column
    cardinality: Literal["many-to-one", "one-to-one", "many-to-many"] = "many-to-one"
    cross_filter_direction: Literal["single", "both"] = "single"
    confidence: Literal["high", "medium", "low"] = "high"
    notes: str = ""  # Rationale or ambiguity explanation


# Normalise common LLM pbi_type variants to the canonical set.
_PARAMETER_PBI_TYPE_ALIASES: dict[str, str] = {
    "decimal": "Number",
    "float": "Number",
    "real": "Number",
    "integer": "Number",
    "int": "Number",
    "double": "Number",
    "number": "Number",
    "string": "Text",
    "str": "Text",
    "text": "Text",
    "date": "Date",
    "datetime": "DateTime",
    "boolean": "Logical",
    "bool": "Logical",
    "logical": "Logical",
}


class ParameterDesign(BaseModel):
    """Design specification for a Power BI parameter.

    Captures the Tableau parameter's domain constraints so the
    downstream semantic model agent can create proper What-If
    parameters with sliders/dropdowns in Power BI.
    """

    name: str  # Display name (no Tableau brackets)
    tableau_name: str  # Original Tableau name (with brackets)
    pbi_type: Literal["Text", "Number", "Date", "DateTime", "Logical"]
    default_value: str  # M literal expression

    @field_validator("pbi_type", mode="before")
    @classmethod
    def normalise_pbi_type(cls, v: str) -> str:
        """Accept common LLM variants and map to canonical values."""
        if isinstance(v, str):
            return _PARAMETER_PBI_TYPE_ALIASES.get(v.lower(), v)
        return v

    domain_type: Literal["range", "list", "all"] = "all"
    # "range": bounded numeric slider; "list": discrete dropdown; "all": open
    range_min: str = ""  # Lower bound (M literal); empty when domain_type != "range"
    range_max: str = ""  # Upper bound (M literal); empty when unbounded
    range_granularity: str = ""  # Step size (M literal); empty when domain_type != "range"
    allowed_values: list[str] = Field(default_factory=list)
    # For domain_type == "list" — the discrete set of allowed values
    description: str = ""  # Business purpose (from functional doc)


class SemanticModelDesign(BaseModel):
    """Complete design specification for the Power BI semantic model.

    Consumed by the Semantic Model Generator Agent to produce TMDL files
    without needing to re-analyse raw Tableau metadata.
    """

    tables: list[TableDesign]
    relationships: list[RelationshipDesign] = Field(default_factory=list)
    parameters: list[ParameterDesign] = Field(default_factory=list)
    source_query_culture: str = "en-US"

    @model_validator(mode="after")
    def check_has_tables(self) -> SemanticModelDesign:
        """At least one table must be defined."""
        if not self.tables:
            raise ValueError("Semantic model design must contain at least one table")
        return self


# ════════════════════════════════════════════════════════════════════════
#  Section 2 — DAX Measures Design
# ════════════════════════════════════════════════════════════════════════

# Normalise common LLM data-type variants to the canonical set.
# The model often returns TMDL-style types (int64, double, dateTime)
# instead of the semantic measure types we expect.
_MEASURE_DATA_TYPE_ALIASES: dict[str, str] = {
    "int64": "integer",
    "int": "integer",
    "long": "integer",
    "number": "real",
    "double": "real",
    "float": "real",
    "float64": "real",
    "decimal": "real",
    "text": "string",
    "str": "string",
    "bool": "boolean",
    "datetime": "datetime",
    "datetype": "date",
}


class MeasureDesign(BaseModel):
    """Design specification for a single DAX measure.

    Pre-analyses each Tableau calculated field and provides the
    downstream DAX agent with a clear translation strategy.
    """

    tableau_name: str  # Original Tableau internal name (e.g. [Calculation_XXX])
    caption: str  # Human-readable name → becomes the DAX measure name
    owner_table: str  # Power BI table that should own this measure
    formula: str  # Original Tableau formula text
    data_type: Literal["string", "integer", "real", "boolean", "date", "datetime"] = "real"
    translatability: Literal["direct", "redesign", "manual"]
    is_hidden: bool = False
    # Whether the measure should be hidden from report consumers.
    # Preserves Tableau's hidden flag — hidden measures are still used
    # as intermediates in other calculations.
    format_string: str = ""
    # DAX format string (e.g. "0.00%", "#,##0", "yyyy-mm-dd").
    # Inferred from Tableau context; empty when unknown.
    is_hidden: bool = False
    # Whether the measure should be hidden from report consumers.
    # Preserves Tableau's hidden flag — hidden measures are still used
    # as intermediates in other calculations.
    format_string: str = ""
    # DAX format string (e.g. "0.00%", "#,##0", "yyyy-mm-dd").
    # Inferred from Tableau context; empty when unknown.

    @field_validator("data_type", mode="before")
    @classmethod
    def normalise_data_type(cls, v: str) -> str:
        """Map common LLM type aliases to canonical measure data types."""
        if isinstance(v, str):
            lowered = v.lower().strip()
            return _MEASURE_DATA_TYPE_ALIASES.get(lowered, lowered)
        return v

    # direct: has a clean DAX equivalent
    # redesign: translatable but requires structural changes (e.g. LOD → CALCULATE)
    # manual: no viable automated translation (table calcs, INDEX, RANK, WINDOW_*)
    target_dax_approach: str = ""
    # Brief description of the DAX approach when translatability != "manual"
    # e.g. "Use CALCULATE + ALLEXCEPT for LOD FIXED equivalent"
    dependencies: list[str] = Field(default_factory=list)
    # Other measure names this measure depends on
    notes: str = ""  # Warnings or caveats for the translation


class UntranslatableItem(BaseModel):
    """A Tableau construct that cannot be automatically translated to DAX."""

    tableau_name: str
    caption: str
    reason: str  # Why it can't be translated
    suggestion: str = ""  # Manual workaround recommendation


class DaxMeasuresDesign(BaseModel):
    """Complete design specification for DAX measures.

    Consumed by the DAX Measures Generator Agent to produce measures.tmdl
    with pre-resolved table assignments and translation strategies.
    """

    measures: list[MeasureDesign] = Field(default_factory=list)
    untranslatable: list[UntranslatableItem] = Field(default_factory=list)


# ════════════════════════════════════════════════════════════════════════
#  Section 3 — Report Design
# ════════════════════════════════════════════════════════════════════════


class FieldBinding(BaseModel):
    """A resolved field reference for a visual encoding.

    Maps a Tableau field reference (which may be a raw `Calculation_XXX`
    or a datasource-scoped field) to its Power BI table.column or
    table.measure equivalent.  The ``well`` field specifies which Power BI
    visual encoding channel the field maps to.
    """

    tableau_field: str  # Original Tableau field identifier
    pbi_table: str  # Resolved Power BI table name
    pbi_field: str  # Resolved Power BI column or measure name
    field_kind: Literal["Column", "Measure", "Aggregation"]
    aggregation: str = "none"
    # e.g. "sum", "avg", "count", "min", "max", "none"
    well: str = ""
    # Power BI visual well / encoding channel this field maps to.
    # Values: "Category" (axis/rows), "Values" (measures/values),
    # "Legend" (series/color), "Tooltips", "Detail", "Size", "".
    # Empty string when the well cannot be determined.


class SortSpec(BaseModel):
    """Sort specification for a visual's data ordering."""

    field: str  # Power BI field name to sort by
    direction: Literal["ASC", "DESC"] = "ASC"
    sort_type: Literal["field", "manual", "computed"] = "field"
    # "field": sort by a column value; "manual": custom fixed order;
    # "computed": sort by a calculated/aggregated value.


class ReferenceLineSpec(BaseModel):
    """Reference/analytics line specification for a visual."""

    line_type: Literal["constant", "average", "median", "min", "max"] = "average"
    field: str = ""  # The measure field this line applies to
    label: str = ""  # Display label (empty = no label)
    notes: str = ""  # Additional context


class InteractionDesign(BaseModel):
    """Design specification for a cross-visual interaction (from Tableau actions)."""

    action_name: str  # Original Tableau action name / ID
    interaction_type: Literal["crossFilter", "drillthrough", "highlight", "none"] = "crossFilter"
    # "crossFilter": clicking one visual filters others (default PBI behaviour)
    # "drillthrough": navigate to detail page
    # "highlight": highlight matching data across visuals
    # "none": no cross-interaction
    source_visual: str = ""  # Worksheet name that triggers the action
    target_fields: list[str] = Field(default_factory=list)
    # PBI field references affected (e.g. "'Ordini'[Regione]")
    notes: str = ""  # Context or limitations


class VisualDesign(BaseModel):
    """Design specification for a single Power BI visual on a page.

    For slicer visuals (visual_type="slicer"), set ``slicer_column``
    to the resolved PBI field reference and ``worksheet_name`` to
    a descriptive name like "Slicer — Categoria".
    """

    worksheet_name: str  # Original Tableau worksheet name (or slicer label)
    visual_type: str  # Power BI visual type (barChart, lineChart, card, slicer, etc.)
    title: str = ""  # Display title for the visual
    display_title: str = ""
    # Tableau worksheet display title (from `title` field in report_input).
    # Distinct from `title` above which is the PBI visual title.
    position: dict[str, int] = Field(default_factory=dict)
    # {x, y, width, height} in Power BI pixels (pre-scaled from Tableau units)
    field_bindings: list[FieldBinding] = Field(default_factory=list)
    # All fields used by this visual, fully resolved to PBI names
    slicer_column: str = ""
    # For slicer visuals only: resolved PBI field reference,
    # e.g. "'Ordini'[Categoria]".  Empty for non-slicer visuals.
    sort_specs: list[SortSpec] = Field(default_factory=list)
    # Sort order applied to this visual's data.
    reference_lines: list[ReferenceLineSpec] = Field(default_factory=list)
    # Analytics/reference lines on the visual (average, median, constant, etc.).
    filters: list[str] = Field(default_factory=list)
    # Human-readable filter descriptions (for non-slicer visuals)
    notes: str = ""  # Any special handling needed


class PageDesign(BaseModel):
    """Design specification for a single Power BI report page."""

    dashboard_name: str  # Original Tableau dashboard name
    display_name: str = ""  # Page display name (defaults to dashboard_name)
    page_order: int = 0  # Display order (0-based); lower = earlier in tab bar
    width: int = 1280  # Page width in pixels
    height: int = 720  # Page height in pixels
    visuals: list[VisualDesign] = Field(default_factory=list)
    interactions: list[InteractionDesign] = Field(default_factory=list)
    # Cross-visual interaction behaviours for this page,
    # derived from Tableau dashboard actions.

    @model_validator(mode="after")
    def default_display_name(self) -> PageDesign:
        """Use dashboard_name as display name if not explicitly set."""
        if not self.display_name:
            self.display_name = self.dashboard_name
        return self


class EntityResolutionMap(BaseModel):
    """Maps Tableau datasource identifiers to Power BI table names.

    This is the central lookup that prevents every downstream agent
    from independently solving the same mapping problem.
    """

    # Key: Tableau federated datasource ID (e.g. "federated.0hgpf0j1fdpvv316shikk0mmdlec")
    # Value: Power BI table name
    datasource_to_table: dict[str, str] = Field(default_factory=dict)

    # Key: Tableau Calculation_XXX internal name
    # Value: DAX measure caption (human-readable name)
    calculated_field_map: dict[str, str] = Field(default_factory=dict)


class ReportDesign(BaseModel):
    """Complete design specification for the Power BI report.

    Consumed by the Report Skeleton and Report Page Visuals agents
    to produce PBIR pages and visuals with pre-resolved field bindings.
    """

    pages: list[PageDesign] = Field(default_factory=list)
    standalone_worksheets: list[str] = Field(default_factory=list)
    # Worksheets not in any dashboard — may become additional pages
    entity_resolution: EntityResolutionMap = Field(
        default_factory=EntityResolutionMap,
    )

    @model_validator(mode="after")
    def check_has_pages(self) -> ReportDesign:
        """At least one page must be defined."""
        if not self.pages:
            raise ValueError("Report design must contain at least one page")
        return self


# ════════════════════════════════════════════════════════════════════════
#  Section 4 — Migration Assessment
# ════════════════════════════════════════════════════════════════════════


class AssessmentWarning(BaseModel):
    """A migration warning or issue identified during TDD analysis."""

    code: str  # Warning code (e.g. WARN_SET, WARN_COMPLEX_CALC, etc.)
    severity: Literal["info", "warning", "error"] = "warning"
    message: str  # Human-readable description
    source_element: str = ""  # Which Tableau element triggered this
    recommendation: str = ""  # Suggested action or workaround


class MigrationAssessment(BaseModel):
    """Cross-cutting migration assessment produced alongside the TDD.

    Consolidates all warnings from both LLM calls and adds an overall
    complexity score and list of manual intervention items.
    """

    complexity_score: Literal["low", "medium", "high"] = "medium"
    # Overall migration complexity based on number of warnings, unsupported
    # constructs, connector complexity, and calculated field density
    summary: str = ""  # Brief assessment narrative
    warnings: list[AssessmentWarning] = Field(default_factory=list)
    manual_items: list[str] = Field(default_factory=list)
    # Specific items that require human review after migration


# ════════════════════════════════════════════════════════════════════════
#  Root Model
# ════════════════════════════════════════════════════════════════════════


class DataModelDesign(BaseModel):
    """Combined output of TDD Call 1 — data model + DAX measures.

    This intermediate model captures both the semantic model design and
    DAX measures design from a single LLM call (they share context and
    need to agree on table names and ownership).
    """

    semantic_model: SemanticModelDesign
    dax_measures: DaxMeasuresDesign
    assessment: MigrationAssessment = Field(default_factory=MigrationAssessment)


class TargetTechnicalDocumentation(BaseModel):
    """Complete Target Technical Documentation for a Tableau → Power BI migration.

    This is the root model that combines all TDD sections.  It is produced
    by the TDD agent and consumed (in parts) by downstream generation agents.
    """

    semantic_model: SemanticModelDesign
    dax_measures: DaxMeasuresDesign
    report: ReportDesign
    assessment: MigrationAssessment = Field(default_factory=MigrationAssessment)
