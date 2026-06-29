"""Pydantic schemas for the Phase 6 notification system.

Three families:
- NotificationOut / NotificationPage: read API.
- NotificationPreferenceIn/Out/Page: per-tenant toggle config.
- SlackWebhookIn/Out: webhook URL config (URL itself is write-only and
  persisted via the Phase 1 vault \u2014 the response only ever returns
  status / channel / last_delivered_at).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from outreach_os.core.config import NotificationEventKey


# ---------- Notification ----------


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_key: NotificationEventKey
    severity: str
    title: str
    body: str | None
    target_type: str | None
    target_id: uuid.UUID | None
    payload: dict[str, Any]
    read_at: datetime | None
    delivered_in_app: bool
    delivered_email: bool
    delivered_slack: bool
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int
    limit: int
    offset: int


class NotificationMarkRead(BaseModel):
    ids: list[uuid.UUID] = Field(default_factory=list)


# ---------- Preferences ----------


class NotificationPreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_key: NotificationEventKey
    channel_in_app: bool
    channel_email_digest: bool
    channel_slack: bool
    updated_at: datetime


class NotificationPreferenceIn(BaseModel):
    event_key: NotificationEventKey
    channel_in_app: bool = True
    channel_email_digest: bool = False
    channel_slack: bool = False


class NotificationPreferencePage(BaseModel):
    items: list[NotificationPreferenceOut]


# ---------- Slack webhook ----------


class SlackWebhookIn(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=64)
    webhook_url: Annotated[str, Field(min_length=10, max_length=2048)]
    channel: str | None = Field(default=None, max_length=64)


class SlackWebhookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    channel: str | None
    status: str
    last_error: str | None
    last_delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


__all__ = [
    "NotificationMarkRead",
    "NotificationOut",
    "NotificationPage",
    "NotificationPreferenceIn",
    "NotificationPreferenceOut",
    "NotificationPreferencePage",
    "SlackWebhookIn",
    "SlackWebhookOut",
]
