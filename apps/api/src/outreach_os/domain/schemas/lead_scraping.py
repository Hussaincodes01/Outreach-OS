"""Pydantic schemas for the lead-scraping subsystem."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from outreach_os.domain.schemas.common import ApiModel, IdTimestampMixin

# --- Source enum (mirrors DB check constraint + LeadSourceKind) ---
VALID_SOURCES = ("serper", "company_site", "linkedin_proxycurl", "social_profiles")


# --- Proxy ---

class ProxyCreate(ApiModel):
    label: str = Field(min_length=1, max_length=200)
    protocol: str = Field(default="http", pattern="^(http|https|socks5)$")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    url: str | None = Field(
        default=None,
        description=(
            "Optional full proxy URL (with optional user:pass@). Stored "
            "encrypted with the per-tenant DEK. If omitted, host:port is used."
        ),
    )


class ProxyOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    label: str
    protocol: str
    host: str
    port: int
    is_active: bool


# --- ICP ---

class IcpCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    industries: list[str] = Field(default_factory=list)
    company_sizes: list[str] = Field(default_factory=list)
    geos: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class IcpUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    industries: list[str] | None = None
    company_sizes: list[str] | None = None
    geos: list[str] | None = None
    titles: list[str] | None = None
    signals: list[str] | None = None
    extra: dict[str, Any] | None = None
    is_active: bool | None = None


class IcpOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    name: str
    description: str | None
    industries: list[str]
    company_sizes: list[str]
    geos: list[str]
    titles: list[str]
    signals: list[str]
    extra: dict[str, Any]
    is_active: bool
    updated_at: datetime


# --- Lead source (per-tenant enabled/disabled source config) ---

class LeadSourceOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    source: str
    is_enabled: bool
    config: dict[str, Any]
    last_run_at: datetime | None


class LeadSourceUpdate(ApiModel):
    is_enabled: bool | None = None
    config: dict[str, Any] | None = None


# --- Lead ---

class LeadOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    source: str
    job_id: uuid.UUID | None
    first_name: str | None
    last_name: str | None
    full_name: str | None
    email: str | None
    domain: str | None
    company_name: str | None
    title: str | None
    linkedin_url: str | None
    country: str | None
    industry: str | None
    company_size: str | None


class LeadPage(ApiModel):
    items: list[LeadOut]
    total: int
    limit: int
    offset: int


# --- Scraping job ---

class ScrapingJobCreate(ApiModel):
    icp_id: uuid.UUID
    sources: list[str] = Field(
        default_factory=lambda: list(VALID_SOURCES),
        description="Subset of sources to run. Defaults to all known sources.",
    )
    requested_count: int = Field(default=50, ge=1, le=500)


class ScrapingJobOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    icp_id: uuid.UUID
    status: str
    sources: list[str]
    requested_count: int
    found_count: int
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
