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
    # True when this mailbox has IMAP settings stored, so the inbox poller
    # will pick it up. Computed from the decrypted config; a decrypt failure
    # reads as False rather than raising out of a list endpoint.
    imap_enabled: bool = False


class SmtpCreate(ApiModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=512)
    email_address: EmailStr
    use_tls: bool = True
    daily_send_cap: int = Field(default=50, ge=1, le=10_000)
    # Optional IMAP settings for inbound reply capture (Task 6). IMAP login
    # reuses the SMTP `username`/`password` above -- most providers (Gmail,
    # Outlook, and generic app-password setups) use the same credentials for
    # both. Omitting `imap_host` leaves the mailbox send-only.
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_use_ssl: bool = True


class SendTestRequest(ApiModel):
    to: EmailStr
    subject: str = Field(default="Outreach OS test", max_length=200)
    body: str = Field(default="Hello from Outreach OS.", max_length=10_000)


class SendTestResult(ApiModel):
    ok: bool
    message: str
