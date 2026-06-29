"""Raw lead — the parser-level representation of a person we found.

The scraping service returns lists of these; the calling code
(Celery task or test) is responsible for mapping them into the
`Lead` model and deduping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RawLead:
    source: str
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    email: str | None = None
    domain: str | None = None
    company_name: str | None = None
    title: str | None = None
    linkedin_url: str | None = None
    country: str | None = None
    industry: str | None = None
    company_size: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)
