"""RelationshipDecision — a relationship between two tables."""

from __future__ import annotations

from pydantic import BaseModel


class RelationshipDecision(BaseModel):
    """A relationship between two tables (always many-to-one, from FK to PK)."""

    from_table: str  # Fact table (many side)
    from_column: str  # Foreign key column
    to_table: str  # Dimension table (one side)
    to_column: str  # Primary key column
    is_active: bool = True  # False when the relationship would create an ambiguous path
