"""Read replies from a mailbox over IMAP and hand them to the reply engine.

The inbound webhook (api/v1/replies.py) stays as the primary path for
providers that support it; this module is the fallback for a mailbox that
only offers IMAP -- poll_mailbox (called from the Celery beat task in
workers/tasks/inbox.py) fetches UNSEEN messages and feeds each one through
the same `ReplyService.ingest` the webhook uses, so threading/dedup/
classification/side-effects are identical either way.
"""
from __future__ import annotations

import asyncio
import contextlib
import imaplib
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.config import get_settings
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.domain.schemas.phase4 import ReplyIngestIn
from outreach_os.services.mailbox.transport import smtp_config
from outreach_os.services.reply_service import ReplyService

log = logging.getLogger(__name__)

FetchFn = Callable[[dict[str, Any]], list[bytes]]


def parse_message(raw: bytes) -> ReplyIngestIn | None:
    """Turn one raw RFC5322 message into a `ReplyIngestIn`, or None if it
    can't be matched/deduped at all (no Message-ID header)."""
    msg = message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        return None
    from_name, from_email = parseaddr(str(msg.get("From") or ""))
    text_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    body_text = text_part.get_content().strip() if text_part is not None else ""
    body_html = html_part.get_content() if html_part is not None else None
    if not body_text:
        body_text = "(no text body)"
    received_at = None
    if msg.get("Date"):
        try:
            received_at = (
                parsedate_to_datetime(str(msg["Date"]))
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
        except (TypeError, ValueError):
            received_at = None
    return ReplyIngestIn(
        message_id_header=message_id,
        from_email=from_email.lower(),
        from_name=from_name or None,
        subject=str(msg.get("Subject") or "") or None,
        body_text=body_text,
        body_html=body_html,
        received_at=received_at,
        in_reply_to=(str(msg.get("In-Reply-To") or "").strip() or None),
        references=(str(msg.get("References") or "").strip() or None),
    )


def fetch_unseen(cfg: dict[str, Any]) -> list[bytes]:
    """Fetch unseen messages from INBOX received in the lookback window,
    marking them seen. Blocking (stdlib imaplib) -- callers must run this
    off the event loop (see `poll_mailbox`)."""
    settings = get_settings()
    host = str(cfg["imap_host"])
    port = int(cfg.get("imap_port") or 993)
    client: imaplib.IMAP4 = (
        imaplib.IMAP4_SSL(host, port)
        if cfg.get("imap_use_ssl", True)
        else imaplib.IMAP4(host, port)
    )
    try:
        client.login(str(cfg["username"]), str(cfg["password"]))
        client.select("INBOX")
        since = (
            datetime.now(timezone.utc) - timedelta(days=settings.inbox_poll_lookback_days)
        ).strftime("%d-%b-%Y")
        status, data = client.search(None, "UNSEEN", "SINCE", since)
        if status != "OK" or not data or not data[0]:
            return []
        out: list[bytes] = []
        for num in data[0].split():
            status, parts = client.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            for part in parts:
                if isinstance(part, tuple) and isinstance(part[1], bytes):
                    out.append(part[1])
            client.store(num, "+FLAGS", "\\Seen")
        return out
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            client.logout()


async def poll_mailbox(
    session: AsyncSession, mailbox: Mailbox, *, fetch: FetchFn = fetch_unseen
) -> int:
    """Fetch unseen IMAP messages for one mailbox and ingest them as replies.

    Returns the number of replies actually ingested (new, not a duplicate,
    and matched to a known Send).

    `fetch` is blocking IMAP I/O, so it runs via `asyncio.to_thread` rather
    than directly on the event loop.

    `ReplyService.ingest` rolls the session back on a duplicate
    Message-ID (IntegrityError on the unique index). Because the RLS tenant
    GUC is set with `set_config(..., true)` (transaction-scoped), it is
    cleared by *both* that rollback and a commit -- so after every message
    we commit on success and re-bind the tenant either way before moving on
    to the next one. Committing per-message (rather than once at the end of
    the mailbox) also means a later message's duplicate-triggered rollback
    can never discard an earlier message's already-ingested reply within
    the same poll.
    """
    cfg = smtp_config(mailbox)
    if not cfg.get("imap_host"):
        return 0
    # Capture before any commit/rollback below: a rollback (unlike a commit,
    # which expire_on_commit=False protects against) always expires every
    # ORM attribute on this object, and re-reading `mailbox.tenant_id`
    # afterwards would trigger a synchronous lazy-load outside of any
    # awaited context (SQLAlchemy's async ORM raises MissingGreenlet for
    # that -- it can't silently do blocking IO on your behalf).
    tenant_id = mailbox.tenant_id
    raws = await asyncio.to_thread(fetch, cfg)
    service = ReplyService(session)
    ingested = 0
    for raw in raws:
        data = parse_message(raw)
        if data is None:
            continue
        result = await service.ingest(tenant_id=tenant_id, data=data)
        if result is not None:
            ingested += 1
            await session.commit()
        await set_tenant_for_session(session, str(tenant_id))
    return ingested


__all__ = ["FetchFn", "fetch_unseen", "parse_message", "poll_mailbox"]
