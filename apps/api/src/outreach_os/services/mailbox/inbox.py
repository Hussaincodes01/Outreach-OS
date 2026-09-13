"""Read replies from a mailbox over IMAP and hand them to the reply engine.

The inbound webhook (api/v1/replies.py) stays as the primary path for
providers that support it; this module is the fallback for a mailbox that
only offers IMAP -- poll_mailbox (called from the Celery beat task in
workers/tasks/inbox.py) fetches UNSEEN messages and feeds each one through
the same `ReplyService.ingest` the webhook uses, so threading/dedup/
classification/side-effects are identical either way.

Fetching and marking `\\Seen` are deliberately two separate IMAP round-trips
(`fetch_unseen` then `mark_seen`): `fetch_unseen` uses `BODY.PEEK[]`, which
never changes flags, so a crash between fetching and durably ingesting a
message leaves it UNSEEN and safe to pick up again on the next poll.
`poll_mailbox` only calls `mark_seen` for uids whose message was actually
committed (or otherwise fully handled) -- see its docstring.
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

FetchFn = Callable[[dict[str, Any]], list[tuple[bytes, bytes]]]
MarkSeenFn = Callable[[dict[str, Any], list[bytes]], None]


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


def _connect(cfg: dict[str, Any]) -> imaplib.IMAP4:
    """Open, log in to, and SELECT INBOX on a fresh IMAP connection.

    Shared by `fetch_unseen` and `mark_seen` -- they never share a live
    connection (each is its own short-lived round-trip), only this setup.
    """
    host = str(cfg["imap_host"])
    port = int(cfg.get("imap_port") or 993)
    client: imaplib.IMAP4 = (
        imaplib.IMAP4_SSL(host, port)
        if cfg.get("imap_use_ssl", True)
        else imaplib.IMAP4(host, port)
    )
    client.login(str(cfg["username"]), str(cfg["password"]))
    client.select("INBOX")
    return client


def fetch_unseen(cfg: dict[str, Any]) -> list[tuple[bytes, bytes]]:
    """Fetch unseen messages from INBOX received in the lookback window.

    Returns `(uid, raw)` pairs. Uses `UID SEARCH` / `UID FETCH ... BODY.PEEK[]`
    throughout -- PEEK never marks a message `\\Seen`, so calling this is
    side-effect-free on the mailbox; see `mark_seen` for the (separate,
    caller-controlled) step that actually flags a message read. Blocking
    (stdlib imaplib) -- callers must run this off the event loop (see
    `poll_mailbox`).
    """
    settings = get_settings()
    client = _connect(cfg)
    try:
        since = (
            datetime.now(timezone.utc) - timedelta(days=settings.inbox_poll_lookback_days)
        ).strftime("%d-%b-%Y")
        status, data = client.uid("SEARCH", "UNSEEN", "SINCE", since)
        if status != "OK" or not data or not data[0]:
            return []
        out: list[tuple[bytes, bytes]] = []
        for uid in data[0].split():
            status, parts = client.uid("FETCH", uid, "(BODY.PEEK[])")
            if status != "OK":
                continue
            for part in parts:
                if isinstance(part, tuple) and isinstance(part[1], bytes):
                    out.append((uid, part[1]))
        return out
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            client.logout()


def mark_seen(cfg: dict[str, Any], uids: list[bytes]) -> None:
    """Flag the given IMAP UIDs `\\Seen`, on a fresh connection.

    Called only for messages whose ingest already committed, so a message
    is never marked seen before it is durably stored -- see `poll_mailbox`.
    A no-op (no connection opened) when `uids` is empty.
    """
    if not uids:
        return
    client = _connect(cfg)
    try:
        joined = b",".join(uids).decode("ascii")
        client.uid("STORE", joined, "+FLAGS", "(\\Seen)")
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            client.logout()


async def poll_mailbox(
    session: AsyncSession,
    mailbox: Mailbox,
    *,
    fetch: FetchFn = fetch_unseen,
    mark_seen: MarkSeenFn = mark_seen,
) -> int:
    """Fetch unseen IMAP messages for one mailbox and ingest them as replies.

    Returns the number of replies actually ingested (new, not a duplicate,
    and matched to a known Send).

    `fetch` is blocking IMAP I/O, so it runs via `asyncio.to_thread` rather
    than directly on the event loop; so does `mark_seen`.

    Durability: `fetch` (`fetch_unseen`) uses IMAP PEEK, so it never marks a
    message `\\Seen` on its own. Each message is only added to `handled`
    -- and so only passed to `mark_seen` at the end -- once it has been
    fully processed: parsed, and either ingested-and-committed or resolved
    as a duplicate/unmatched-send `None` from `ReplyService.ingest` (which
    already committed or is a clean no-op). A crash between `fetch` and a
    given message's commit leaves that message UNSEEN, so it is simply
    re-fetched (and, since ingest is idempotent on Message-ID, safely
    re-ingested-as-duplicate-or-ingested) on the next poll.

    Isolation: one bad message (malformed body that makes `parse_message`
    raise, or any non-`IntegrityError` exception out of `ingest`) must not
    abort the rest of the mailbox's batch. Each message runs inside its own
    try/except; a failure is logged (mailbox id + Message-ID when parsed --
    never body text or credentials) and the loop continues with that uid
    left out of `handled`, so it is retried on the next poll instead of
    being lost.

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
    mailbox_id = mailbox.id
    raws = await asyncio.to_thread(fetch, cfg)
    service = ReplyService(session)
    ingested = 0
    handled: list[bytes] = []
    for uid, raw in raws:
        data: ReplyIngestIn | None = None
        try:
            data = parse_message(raw)
            if data is None:
                handled.append(uid)
                continue
            result = await service.ingest(tenant_id=tenant_id, data=data)
            if result is not None:
                ingested += 1
                await session.commit()
            await set_tenant_for_session(session, str(tenant_id))
            handled.append(uid)
        except Exception:
            await session.rollback()
            await set_tenant_for_session(session, str(tenant_id))
            log.warning(
                "inbox poll: failed to process message mailbox=%s message_id=%s",
                mailbox_id, data.message_id_header if data is not None else None,
                exc_info=True,
            )
    if handled:
        await asyncio.to_thread(mark_seen, cfg, handled)
    return ingested


__all__ = ["FetchFn", "MarkSeenFn", "fetch_unseen", "mark_seen", "parse_message", "poll_mailbox"]
