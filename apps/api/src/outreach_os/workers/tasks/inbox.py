"""Celery task: poll every mailbox's own IMAP inbox for new replies.

Async core + sync Celery wrapper, same pattern as workers/tasks/send.py /
send_tasks.py -- both pieces live in this one module because the plan's
file list has a single `workers/tasks/inbox.py` (no `_tasks.py` sibling).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

from outreach_os.core.db import get_session_factory, run_worker_task
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.services.local_workspace import LOCAL_TENANT_ID
from outreach_os.services.mailbox.inbox import FetchFn, MarkSeenFn, fetch_unseen, poll_mailbox
from outreach_os.services.mailbox.inbox import mark_seen as mark_seen_default
from outreach_os.workers.celery_app import celery_app

log = logging.getLogger(__name__)


async def poll_inboxes_async(
    *, fetch: FetchFn | None = None, mark_seen: MarkSeenFn | None = None
) -> dict[str, int]:
    """Poll every active SMTP mailbox in the local workspace for replies.

    Only the mailbox *ids* are selected up front. Each mailbox is then
    loaded and polled in its own fresh session, inside its own try/except,
    so a single bad mailbox (unreachable host, rejected login, no IMAP
    settings, a duplicate-triggered rollback, anything else) is logged and
    counted in `errors` rather than aborting the rest of the run.

    Why a session per mailbox: a rollback expires every ORM object loaded in
    that session. With one shared session, a failure (or a per-message
    rollback inside `poll_mailbox`) expired the mailboxes not yet processed,
    and the next one's attribute access raised `MissingGreenlet`, killing
    the whole task. A fresh session per mailbox means one mailbox's rollback
    can never touch another mailbox's state.

    A failure inside `mark_seen` (e.g. the connection drops between fetching
    and flagging) lands in the guard too: the ingests already committed
    stand, and the affected messages are simply re-fetched (and safely
    re-ingested as duplicates, or ingested for the first time) on the next
    poll.
    """
    fetch_fn = fetch or fetch_unseen
    mark_seen_fn = mark_seen or mark_seen_default
    factory = get_session_factory()
    mailboxes = 0
    ingested_total = 0
    errors = 0
    async with factory() as session:
        await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
        mailbox_ids = list(
            (
                await session.execute(
                    select(Mailbox.id)
                    .where(
                        Mailbox.tenant_id == LOCAL_TENANT_ID,
                        Mailbox.provider == "smtp",
                        Mailbox.is_active.is_(True),
                    )
                    .order_by(Mailbox.created_at, Mailbox.id)
                )
            ).scalars().all()
        )

    for mailbox_id in mailbox_ids:
        try:
            async with factory() as session:
                await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
                mailbox = await session.get(Mailbox, mailbox_id)
                if mailbox is None:
                    # Deleted between selecting the ids and getting here.
                    continue
                mailboxes += 1
                ingested_total += await poll_mailbox(
                    session, mailbox, fetch=fetch_fn, mark_seen=mark_seen_fn
                )
                await session.commit()
        except Exception:
            # Mailbox id only (plus the traceback): never the message body or
            # the mailbox's credentials.
            log.warning("inbox poll failed mailbox=%s", mailbox_id, exc_info=True)
            errors += 1
    return {"mailboxes": mailboxes, "ingested": ingested_total, "errors": errors}


@celery_app.task(name="outreach_os.workers.poll_inboxes")  # type: ignore[untyped-decorator]
def poll_inboxes() -> dict[str, int]:
    """Celery wrapper. In eager mode this runs the async core on a
    brand-new event loop in a thread, then returns."""
    log.info("poll_inboxes start")
    started = datetime.utcnow()
    summary = run_worker_task(poll_inboxes_async())
    log.info(
        "poll_inboxes done in %ss: %s",
        (datetime.utcnow() - started).total_seconds(), summary,
    )
    return summary


__all__ = ["poll_inboxes", "poll_inboxes_async"]
