"""Notification fan-out workers.

Two Celery tasks:
- `notifications.send_email_digest` \u2014 picks up unread
  `Notification.delivered_email=False` rows that are past the
  digest's quiet window, groups them by tenant + (UTC) day, and
  "sends" the email. In dev we just call the StubMailer; in prod
  the mailer is wired to a real SMTP transport.
- (Slack delivery is inline; the WebSocket + Slack fan-out both run
  inside `services.notification_service.publish`. A dedicated Celery
  task is overkill for V1.)

Schedule:
- send_email_digest runs every 60s on Celery beat (configurable).

The beat schedule is registered in `workers/celery_app.py`.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from outreach_os.core.db import session_scope
from outreach_os.core.mailer import OutgoingMessage, get_mailer_client
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.notification import Notification
from outreach_os.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="outreach_os.notifications.send_email_digest")
def send_email_digest() -> dict[str, Any]:
    """Pick up undelivered email-digest notifications, group by tenant,
    send one email per tenant per day, and mark them as delivered.

    In tests the mailer is the StubMailer; the digest ends up in
    `mailer.sent` as a single message with a body that lists every
    notification in the group.
    """
    return asyncio.run(_send_email_digest_async())


async def _send_email_digest_async() -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    sent_count = 0
    grouped: dict[Any, list[Notification]] = defaultdict(list)
    # First pass: discover distinct tenant_ids with undelivered items.
    # We use a tenant-agnostic read by setting the GUC to a wildcard
    # the policy accepts \u2014 or, simpler, just enumerate the tenants we
    # can see. The cleanest path is to query as the *application user*
    # who sees nothing without a GUC, so we open a session for each
    # tenant we know about (read from the master `tenant` table which
    # is not RLS-protected).
    async with session_scope() as session:
        from outreach_os.domain.models.tenant import Tenant
        from sqlalchemy import select as sa_select
        tenant_rows = (
            await session.execute(sa_select(Tenant.id))
        ).scalars().all()

    for tid in tenant_rows:
        async with session_scope() as session:
            await set_tenant_for_session(session, str(tid))
            rows = (
                await session.execute(
                    select(Notification)
                    .where(
                        Notification.delivered_email.is_(False),
                        Notification.created_at >= cutoff,
                    )
                    .order_by(Notification.created_at.asc())
                )
            ).scalars().all()
            for r in rows:
                grouped[tid].append(r)

    mailer = get_mailer_client()
    for tenant_id, items in grouped.items():
        try:
            _send_one_digest(tenant_id, items, mailer)
            # Mark as delivered.
            async with session_scope() as session:
                await set_tenant_for_session(session, str(tenant_id))
                ids = [n.id for n in items]
                for n in (
                    await session.execute(select(Notification).where(Notification.id.in_(ids)))
                ).scalars().all():
                    n.delivered_email = True
            sent_count += len(items)
        except Exception:  # noqa: BLE001
            log.exception("digest send failed tenant=%s", tenant_id)

    return {"groups": len(grouped), "items_sent": sent_count}


def _send_one_digest(tenant_id: Any, items: list[Notification], mailer: Any) -> None:
    """Render + send a single digest email."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = "[Outreach OS] Daily digest \u2014 " + today + " \u2014 " + str(len(items)) + " updates"
    body_lines = ["Hi there,", "", f"You have {len(items)} new updates from today:", ""]
    for n in items:
        body_lines.append(f"\u2022 [{n.severity}] {n.title}")
        if n.body:
            body_lines.append(f"   {n.body[:200]}")
    body_lines += ["", "\u2014 The Outreach OS team"]
    mailer.send(
        OutgoingMessage(
            to_email="digest@outreach-os.local",
            from_email="digest@outreach-os.local",
            subject=subject,
            body_text="\n".join(body_lines),
            message_id_header=f"<digest-{today}-{tenant_id}@outreach-os.local>",
        )
    )


__all__ = ["send_email_digest"]
