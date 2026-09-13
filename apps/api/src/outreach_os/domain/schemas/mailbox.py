"""Mailbox schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from outreach_os.domain.schemas.common import ApiModel


class MailboxOut(ApiModel):
    id: uuid.UUID
    provider: str
    email_address: EmailStr
    is_active: bool
    daily_send_cap: int
    created_at: datetime


class SmtpCreate(ApiModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=512)
    email_address: EmailStr
    use_tls: bool = True
    daily_send_cap: int = Field(default=50, ge=1, le=10_000)


class SendTestRequest(ApiModel):
    to: EmailStr
    subject: str = Field(default="Outreach OS test", max_length=200)
    body: str = Field(default="Hello from Outreach OS.", max_length=10_000)
