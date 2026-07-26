"""Pydantic schemas for the Phase 4 send + reply + follow-up engine."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from outreach_os.domain.schemas.common import ApiModel, IdTimestampMixin

# --- Sequence run ---

SEQUENCE_RUN_STATUSES = ("running", "paused", "stopped", "completed")


class SequenceRunStartIn(ApiModel):
    campaign_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    lead_ids: list[uuid.UUID] = Field(min_length=1)
    # When to fire the first email; follow-ups are scheduled by step.delay_days.
    start_at: datetime | None = None
    # Skip the per-mailbox daily cap check (used by the e2e demo).
    ignore_caps: bool = False


class SequenceStepOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    run_id: uuid.UUID
    lead_id: uuid.UUID
    campaign_step_id: uuid.UUID
    draft_id: uuid.UUID | None
    status: str
    scheduled_at: datetime
    sent_at: datetime | None
    last_reply_at: datetime | None
    stop_reason: str | None
    attempts: int
    updated_at: datetime


class SequenceRunOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    status: str
    stopped_reason: str | None
    started_at: datetime
    stopped_at: datetime | None
    updated_at: datetime
    step_count: int = 0
    pending_count: int = 0
    sent_count: int = 0
    replied_count: int = 0
    stopped_count: int = 0


# --- Send ---

SEND_STATUSES = ("queued", "sent", "bounced", "failed", "unsubscribed", "skipped")


class SendOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    step_id: uuid.UUID
    mailbox_id: uuid.UUID | None
    draft_id: uuid.UUID | None
    to_email: str
    from_email: str
    subject: str
    body_text: str
    message_id_header: str
    provider_message_id: str | None
    status: str
    error: str | None
    queued_at: datetime
    sent_at: datetime | None
    opened_at: datetime | None
    clicked_at: datetime | None


class SendPage(ApiModel):
    items: list[SendOut]
    total: int
    limit: int
    offset: int


# --- Reply ---

REPLY_CLASSIFICATIONS = (
    "positive", "negative", "ooo", "question",
    "unsubscribe", "bounce", "other",
)


class ReplyIngestIn(ApiModel):
    """Inbound webhook payload (Gmail Pub/Sub / SendGrid Inbound / SES SNS)."""
    message_id_header: str = Field(min_length=1)
    from_email: str
    from_name: str | None = None
    subject: str | None = None
    body_text: str = Field(min_length=1)
    body_html: str | None = None
    received_at: datetime | None = None
    # The In-Reply-To / References headers, used to find the original Send.
    in_reply_to: str | None = None
    references: str | None = None


class ReplyOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    send_id: uuid.UUID
    message_id_header: str
    from_email: str
    from_name: str | None
    subject: str | None
    body_text: str
    received_at: datetime
    classification: str | None
    classification_confidence: float | None
    classified_at: datetime | None


class ReplyPage(ApiModel):
    items: list[ReplyOut]
    total: int
    limit: int
    offset: int


# --- Tracking ---

TRACKING_EVENT_TYPES = ("open", "click")


# --- Suppression ---

SUPPRESSION_REASONS = ("unsubscribe", "bounce", "complaint", "manual")


class SuppressionCreateIn(ApiModel):
    email: str
    reason: str
    source: str | None = None
    notes: str | None = None


class SuppressionOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    email: str
    reason: str
    source: str | None
    notes: str | None


class SuppressionPage(ApiModel):
    items: list[SuppressionOut]
    total: int
    limit: int
    offset: int
