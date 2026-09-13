"""Mailbox schemas."""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import Field, field_validator

from outreach_os.domain.schemas.common import ApiModel

# Deliberately permissive syntax check, not pydantic's `EmailStr`. The
# `email-validator` package backing `EmailStr` rejects any address whose
# domain is on the RFC 2606 "special-use" list (`.test`, `.example`,
# `.invalid`, `.localhost`) as "a special-use or reserved name that cannot
# be used with email" -- which blocks connecting a mailbox to a local/dev
# mail server such as the GreenMail instance this project's own e2e smoke
# test (and any operator's local testing) uses. Mirrors the lead-import
# email regex (`services/lead_import.py`): reject obvious junk, accept
# everything else and let the real SMTP/IMAP exchange be the authority on
# deliverability.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def _validate_email(value: str) -> str:
    value = value.strip()
    if not _EMAIL_RE.match(value):
        raise ValueError("value is not a valid email address")
    return value


class MailboxOut(ApiModel):
    id: uuid.UUID
    provider: str
    email_address: str
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
    email_address: str
    use_tls: bool = True
    daily_send_cap: int = Field(default=50, ge=1, le=10_000)
    # Optional IMAP settings for inbound reply capture (Task 6). IMAP login
    # reuses the SMTP `username`/`password` above -- most providers (Gmail,
    # Outlook, and generic app-password setups) use the same credentials for
    # both. Omitting `imap_host` leaves the mailbox send-only.
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_use_ssl: bool = True

    @field_validator("email_address")
    @classmethod
    def _check_email_address(cls, v: str) -> str:
        return _validate_email(v)


class SendTestRequest(ApiModel):
    to: str
    subject: str = Field(default="Outreach OS test", max_length=200)
    body: str = Field(default="Hello from Outreach OS.", max_length=10_000)

    @field_validator("to")
    @classmethod
    def _check_to(cls, v: str) -> str:
        return _validate_email(v)
