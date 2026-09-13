"""Celery task: poll every mailbox's own IMAP inbox for new replies.

Async core + sync Celery wrapper, same pattern as workers/tasks/send.py /
send_tasks.py -- both pieces live in this one module because the plan's
file list has a single `workers/tasks/inbox.py` (no `_tasks.py` sibling).
"""
from __future__ import annotations

import asyncio
import imaplib
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from outreach_os.core.db import get_session_factory
from outreach_os.core.errors import MailError
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.services.local_workspace import LOCAL_TENANT_ID
from outreach_os.services.mailbox.inbox import FetchFn, fetch_unseen, poll_mailbox
from outreach_os.workers.celery_app import celery_app

log = logging.getLogger(__name__)


async def poll_inboxes_async(*, fetch: FetchFn | None = None) -> dict[str, int]:
    """Poll every active SMTP mailbox in the local workspace for replies.

    Runs one mailbox at a time, each inside its own try/except so a single
    bad mailbox (unreachable host, rejected login, no IMAP settings at all)
    is logged and counted in `errors` rather than aborting the rest of the
    run -- the whole point of polling N mailboxes is that one broken one
    must not stop replies from being captured on the others.
    """
    fetch_fn = fetch or fetch_unseen
    factory = get_session_factory()
    mailboxes = 0
    ingested_total = 0
    errors = 0
    async with factory() as session:
        await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
        rows = await session.execute(
            select(Mailbox).where(
                Mailbox.tenant_id == LOCAL_TENANT_ID,
                Mailbox.provider == "smtp",
                Mailbox.is_active.is_(True),
            )
        )
        for mailbox in rows.scalars().all():
            mailboxes += 1
            # Capture before poll_mailbox can commit/rollback -- a rollback
            # expires every attribute on `mailbox`, and this loop (unlike
            # poll_mailbox) has no other reason to re-read it afterwards.
            mailbox_id = mailbox.id
            try:
                ingested_total += await poll_mailbox(session, mailbox, fetch=fetch_fn)
                await session.commit()
            except (MailError, imaplib.IMAP4.error, OSError) as exc:
                log.warning("inbox poll failed mailbox=%s: %s", mailbox_id, exc)
                errors += 1
                await session.rollback()
            # Commit and rollback both end the transaction, which clears the
            # transaction-scoped RLS GUC -- re-bind before the next mailbox.
            await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
    return {"mailboxes": mailboxes, "ingested": ingested_total, "errors": errors}


@celery_app.task(name="outreach_os.workers.poll_inboxes")  # type: ignore[untyped-decorator]
def poll_inboxes() -> dict[str, Any]:
    """Celery wrapper. In eager mode this runs the async core on a
    brand-new event loop in a thread, then returns."""
    log.info("poll_inboxes start")
    started = datetime.utcnow()
    summary = asyncio.run(poll_inboxes_async())
    log.info(
        "poll_inboxes done in %ss: %s",
        (datetime.utcnow() - started).total_seconds(), summary,
    )
    return summary


__all__ = ["poll_inboxes", "poll_inboxes_async"]
