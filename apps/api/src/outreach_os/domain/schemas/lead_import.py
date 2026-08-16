"""Schemas for the CSV lead import flow."""
from __future__ import annotations

from pydantic import Field

from outreach_os.domain.schemas.common import ApiModel


class ImportPreviewOut(ApiModel):
    """What we read from the file, plus our guess at the column mapping.

    Returned before anything is written so the user can correct the mapping —
    importing thousands of rows into the wrong fields is far more expensive
    than one confirmation step.
    """

    headers: list[str]
    sample_rows: list[dict[str, str]]
    # column header -> lead field
    suggested_mapping: dict[str, str]
    importable_fields: list[str]
    total_rows: int
    # True when the file holds more rows than a single import accepts.
    truncated: bool
    max_rows: int


class RowProblemOut(ApiModel):
    row_number: int
    reason: str


class ImportResultOut(ApiModel):
    imported: int
    duplicates: int
    skipped: int
    total_rows: int
    # Capped in the response; the counts above are complete.
    problems: list[RowProblemOut] = Field(default_factory=list)
