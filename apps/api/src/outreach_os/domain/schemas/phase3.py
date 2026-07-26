"""Pydantic schemas for the Phase 3 agent subsystem (campaigns, RAG, drafts)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from outreach_os.domain.schemas.common import ApiModel, IdTimestampMixin

# --- Campaign ---

CAMPAIGN_STATUSES = ("draft", "active", "paused", "archived")


class CampaignStepIn(ApiModel):
    step_number: int = Field(ge=1)
    delay_days: int = Field(default=0, ge=0)
    subject_template: str = Field(min_length=1, max_length=500)
    goal: str | None = None


class CampaignStepOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    campaign_id: uuid.UUID
    step_number: int
    delay_days: int
    subject_template: str
    goal: str | None


class CampaignCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    # Up to 3 sample emails. We enforce the cap at the service layer.
    style_sample_emails: list[str] = Field(default_factory=list, max_length=3)
    style_notes: str | None = None
    llm_model: str | None = None
    steps: list[CampaignStepIn] = Field(default_factory=list)


class CampaignUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None
    style_sample_emails: list[str] | None = Field(default=None, max_length=3)
    style_notes: str | None = None
    llm_model: str | None = None
    is_active: bool | None = None


class CampaignOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    name: str
    description: str | None
    status: str
    llm_model: str | None
    style_sample_emails: list[str]
    style_notes: str | None
    is_active: bool
    steps: list[CampaignStepOut] = Field(default_factory=list)
    updated_at: datetime


class CampaignSummary(IdTimestampMixin):
    """Lightweight version of CampaignOut — no steps, no style samples.
    Used in list endpoints to keep payloads small."""
    tenant_id: uuid.UUID
    name: str
    description: str | None
    status: str
    llm_model: str | None
    is_active: bool


# --- Knowledge base ---

class KnowledgeBaseItemCreate(ApiModel):
    title: str = Field(min_length=1, max_length=300)
    source: str | None = None
    body: str = Field(min_length=1)


class KnowledgeBaseItemOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    title: str
    source: str | None
    body: str
    chunk_count: int = 0


class KnowledgeBaseItemSummary(IdTimestampMixin):
    tenant_id: uuid.UUID
    title: str
    source: str | None
    chunk_count: int = 0


class KnowledgeBaseItemPage(ApiModel):
    items: list[KnowledgeBaseItemSummary]
    total: int
    limit: int
    offset: int


# --- Draft ---

DRAFT_STATUSES = ("pending", "ready", "approved", "rejected", "sent", "failed")


class DraftOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    campaign_id: uuid.UUID
    lead_id: uuid.UUID
    step_id: uuid.UUID
    status: str
    subject: str | None
    body_preview: str | None
    s3_key: str | None
    model_used: str | None
    error: str | None
    # Set by the GET single-draft endpoint only.
    body: str | None = None
    download_url: str | None = None
    updated_at: datetime


class DraftPage(ApiModel):
    items: list[DraftOut]
    total: int
    limit: int
    offset: int


class DraftUpdate(ApiModel):
    status: str | None = None
    subject: str | None = None
    body: str | None = None
    body_preview: str | None = None


# --- Agent run ---

class AgentRunOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    campaign_id: uuid.UUID
    draft_id: uuid.UUID | None
    status: str
    trace: dict[str, Any]
    input_tokens: int
    output_tokens: int
    embeddings_tokens: int
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None


class GenerateDraftIn(ApiModel):
    lead_id: uuid.UUID
    step_id: uuid.UUID
    # If true, replace any existing draft for this (lead, step) pair.
    force_regenerate: bool = False
