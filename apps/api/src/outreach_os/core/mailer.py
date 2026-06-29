"""Mailer abstraction — provider-agnostic send/receive surface.

The default in dev / tests is `StubMailer`, which records every send
in-memory and returns a synthetic provider_message_id. Real adapters
(Gmail via Graph API, SendGrid, Mailgun) implement the same Protocol
and can be swapped in via `get_mailer_client()` based on settings.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)


class MailerError(RuntimeError):
    """Wraps any provider failure (auth, rate limit, 4xx, network)."""


@dataclass
class OutgoingMessage:
    """One email handed to the mailer for delivery."""
    to_email: str
    from_email: str
    subject: str
    body_text: str
    body_html: str | None = None
    # RFC5322 Message-ID the caller pre-generated. Required for thread
    # tracking (replies use In-Reply-To / References).
    message_id_header: str = ""
    # In-Reply-To of a previous message, if this is part of a thread.
    in_reply_to: str | None = None
    references: str | None = None
    # Custom headers the mailer should preserve.
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class SendReceipt:
    """The provider's acknowledgement of a sent message."""
    provider_message_id: str
    accepted: bool = True
    # Free-form provider response for logging / debugging.
    raw: dict[str, Any] | None = None


class MailerClient(Protocol):
    """The interface SendService depends on."""

    def send(self, message: OutgoingMessage) -> SendReceipt: ...


class StubMailer:
    """Default mailer for dev / tests.

    Records every sent message in `self.sent` so tests can assert on the
    outbound queue. Returns a synthetic provider_message_id derived from
    a random token. Throws `MailerError` only when a test wants it to.
    """

    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []
        self.should_fail = False

    def send(self, message: OutgoingMessage) -> SendReceipt:
        if self.should_fail:
            raise MailerError("stub mailer configured to fail")
        self.sent.append(message)
        log.info(
            "stub-mailer sent to=%s subject=%r message_id=%s",
            message.to_email, message.subject[:60], message.message_id_header,
        )
        return SendReceipt(
            provider_message_id=f"stub-{secrets.token_hex(8)}",
            accepted=True,
            raw={"stub": True},
        )

    def reset(self) -> None:
        self.sent = []
        self.should_fail = False


_default_mailer: MailerClient | None = None


def get_mailer_client() -> MailerClient:
    """Return the process-wide mailer.

    Default is the StubMailer. Tests and the e2e demo inject their own
    stub by calling `set_mailer_client`.
    """
    global _default_mailer
    if _default_mailer is None:
        _default_mailer = StubMailer()
    return _default_mailer


def set_mailer_client(client: MailerClient | None) -> None:
    """Override the default mailer. Pass None to reset."""
    global _default_mailer
    _default_mailer = client


__all__ = [
    "MailerClient",
    "MailerError",
    "OutgoingMessage",
    "SendReceipt",
    "StubMailer",
    "get_mailer_client",
    "set_mailer_client",
]
