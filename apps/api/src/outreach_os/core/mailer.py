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


class SmtpMailer:
    """Transactional email over the platform's own SMTP server.

    Distinct from `services.mailbox.mailer`, which sends campaign mail through
    each tenant's own mailbox. Password resets and verification links must come
    from us, not from the customer's outbound identity — a reset arriving from
    a prospect-facing address is both confusing and a deliverability problem.

    Synchronous by design: callers already run it off the event loop, and the
    stdlib SMTP client keeps this dependency-free.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        default_from: str,
        timeout: int = 10,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._default_from = default_from
        self._timeout = timeout

    def send(self, message: OutgoingMessage) -> SendReceipt:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = message.from_email or self._default_from
        msg["To"] = message.to_email
        msg["Subject"] = message.subject
        if message.message_id_header:
            msg["Message-ID"] = message.message_id_header
        for key, value in message.headers.items():
            msg[key] = value
        msg.set_content(message.body_text)
        if message.body_html:
            msg.add_alternative(message.body_html, subtype="html")

        try:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as client:
                if self._use_tls:
                    client.starttls()
                if self._username and self._password:
                    client.login(self._username, self._password)
                client.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailerError(f"SMTP delivery failed: {exc}") from exc

        return SendReceipt(
            provider_message_id=message.message_id_header or f"smtp-{secrets.token_hex(8)}",
            accepted=True,
        )


_default_mailer: MailerClient | None = None

# Tracks exactly what `set_mailer_client` installed, independent of
# `_default_mailer`'s lazy-init fallback. Campaign sends must never silently
# fall back to the platform SmtpMailer/StubMailer the way `get_mailer_client`
# does — `get_mailer_override` lets a caller ask "is there a test override?"
# and get a plain None when there isn't, instead of a freshly constructed
# platform mailer.
_override: MailerClient | None = None


def get_mailer_client() -> MailerClient:
    """Return the process-wide mailer.

    Uses real SMTP when `SMTP_HOST` is configured, otherwise the StubMailer.
    Selecting on an explicitly-set host (rather than defaulting to localhost)
    means a deployment that forgot to configure mail logs its messages instead
    of failing every request against a server that isn't there — and the test
    suite never opens a socket.
    """
    global _default_mailer
    if _default_mailer is None:
        from outreach_os.core.config import get_settings

        settings = get_settings()
        if settings.smtp_host:
            _default_mailer = SmtpMailer(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username or None,
                password=(
                    settings.smtp_password.get_secret_value()
                    if settings.smtp_password
                    else None
                ),
                use_tls=settings.smtp_use_tls,
                default_from=settings.transactional_from_email,
            )
        else:
            _default_mailer = StubMailer()
    return _default_mailer


def set_mailer_client(client: MailerClient | None) -> None:
    """Override the default mailer. Pass None to reset."""
    global _default_mailer, _override
    _default_mailer = client
    _override = client


def get_mailer_override() -> MailerClient | None:
    """The client installed via `set_mailer_client`, or None.

    Unlike `get_mailer_client`, this never lazily constructs a platform
    mailer — callers (e.g. `SendService`) use it to distinguish "a test
    installed an override" from "nothing installed one", so they can fall
    through to the mailbox's own SMTP transport instead of a shared one.
    """
    return _override


# Transactional mail is tracked separately from campaign mail on purpose.
# They travel over different transports (our SMTP vs the tenant's mailbox) and
# must not share an outbox: a password reset appearing in a campaign's sent
# list is both a wrong abstraction and, in tests, a source of index-shifting
# surprises.
_transactional_mailer: MailerClient | None = None


def get_transactional_mailer() -> MailerClient:
    """Mailer for platform email (resets, verification).

    Falls back to the campaign mailer's selection logic — real SMTP when
    configured, StubMailer otherwise — but keeps its own instance.
    """
    global _transactional_mailer
    if _transactional_mailer is None:
        from outreach_os.core.config import get_settings

        settings = get_settings()
        if settings.smtp_host:
            _transactional_mailer = SmtpMailer(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username or None,
                password=(
                    settings.smtp_password.get_secret_value()
                    if settings.smtp_password
                    else None
                ),
                use_tls=settings.smtp_use_tls,
                default_from=settings.transactional_from_email,
            )
        else:
            _transactional_mailer = StubMailer()
    return _transactional_mailer


def set_transactional_mailer(client: MailerClient | None) -> None:
    """Override the transactional mailer. Pass None to reset."""
    global _transactional_mailer
    _transactional_mailer = client


__all__ = [
    "MailerClient",
    "MailerError",
    "OutgoingMessage",
    "SendReceipt",
    "SmtpMailer",
    "StubMailer",
    "get_mailer_client",
    "get_mailer_override",
    "get_transactional_mailer",
    "set_mailer_client",
    "set_transactional_mailer",
]
