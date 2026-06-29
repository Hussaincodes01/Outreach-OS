"""Notification service \u2014 the fan-out point.

`publish(tenant_id, event_key, ...)` is called by the reply service,
the meeting service, the send engine, etc. The service:

1. Looks up tenant NotificationPreference for this event_key.
2. Inserts a `Notification` row in the DB (in-app channel is on by default).
3. Broadcasts to the WebSocket channel.
4. Enqueues async fan-out tasks (Slack worker + email digest aggregator)
   for any extra channels that are enabled.

The `publish` call is non-blocking *from the caller's perspective* \u2014
we commit the row first, then fire the WS broadcast and dispatch the
async fan-out. Any failure in the fan-out is logged but never propagates
back, because the notification is already in the DB.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.config import get_settings
from outreach_os.core.slack_client import get_slack_client
from outreach_os.core.ws_manager import get_ws_manager
from outreach_os.domain.models.notification import Notification
from outreach_os.domain.models.notification_preference import NotificationPreference
from outreach_os.domain.models.slack_webhook import SlackWebhook

logger = logging.getLogger(__name__)


async def _preference_for(
    db: AsyncSession, tenant_id: uuid.UUID, event_key: str
) -> NotificationPreference | None:
    return (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.tenant_id == tenant_id,
                NotificationPreference.event_key == event_key,
            )
        )
    ).scalar_one_or_none()


def _resolved_channels(
    pref: NotificationPreference | None, event_key: str
) -> tuple[bool, bool, bool]:
    """Return (in_app, email_digest, slack) after applying defaults."""
    settings = get_settings()
    if pref is None:
        return (
            settings.notification_default_channel_in_app,
            settings.notification_default_channel_email_digest,
            settings.notification_default_channel_slack,
        )
    return (
        pref.channel_in_app,
        pref.channel_email_digest,
        pref.channel_slack,
    )


def _to_event_dict(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "event_key": n.event_key,
        "severity": n.severity,
        "title": n.title,
        "body": n.body,
        "target_type": n.target_type,
        "target_id": str(n.target_id) if n.target_id else None,
        "payload": n.payload,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat(),
    }


async def publish(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_key: str,
    title: str,
    body: str | None = None,
    severity: str = "info",
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> Notification:
    """Persist a notification and fan out to all enabled channels.

    Returns the persisted Notification. The WebSocket broadcast and
    Slack fan-out are best-effort \u2014 any failure is logged and
    swallowed. The email-digest channel simply records the row with
    `delivered_email=false`; the beat job picks it up later.
    """
    settings = get_settings()
    if event_key not in settings.notification_event_keys:
        logger.warning("notification: unknown event_key=%s", event_key)
        # We still record the event \u2014 the system should be tolerant of
        # event_keys added between deployments.

    pref = await _preference_for(db, tenant_id, event_key)
    in_app, email_digest, slack = _resolved_channels(pref, event_key)

    n = Notification(
        tenant_id=tenant_id,
        event_key=event_key,
        severity=severity,
        title=title,
        body=body,
        target_type=target_type,
        target_id=target_id,
        payload=payload or {},
        delivered_in_app=in_app,
        delivered_email=False,
        delivered_slack=False,
    )
    db.add(n)
    await db.flush()  # assign id, created_at, etc.

    # 1. In-app + WebSocket \u2014 only fire if the in-app channel is on
    #    (otherwise the row still exists for the email digest).
    if in_app:
        try:
            await get_ws_manager().broadcast(tenant_id, _to_event_dict(n))
            n.delivered_in_app = True
        except Exception as e:
            logger.warning("notification: ws broadcast failed: %s", e)

    # 2. Slack \u2014 best-effort, never raises.
    if slack:
        try:
            await _fan_out_slack(db, tenant_id, n)
        except Exception as e:
            logger.warning("notification: slack fan-out failed: %s", e)

    # 3. Email digest \u2014 the row stays with delivered_email=False and
    #    the beat job in workers/tasks/notifications.py picks it up.
    if email_digest:
        logger.info("notification: queued for email digest tenant=%s key=%s",
                    tenant_id, event_key)

    return n


async def _fan_out_slack(
    db: AsyncSession, tenant_id: uuid.UUID, n: Notification
) -> None:
    """Deliver one notification to all active Slack webhooks for the tenant."""
    hooks = (
        await db.execute(
            select(SlackWebhook).where(
                SlackWebhook.tenant_id == tenant_id,
                SlackWebhook.status == "active",
            )
        )
    ).scalars().all()
    if not hooks:
        return

    from outreach_os.services.credential_lookup import get_decrypted_credential

    client = get_slack_client()
    for hook in hooks:
        if not hook.webhook_url_credential_id:
            continue
        cred = await get_decrypted_credential(
            db, tenant_id=tenant_id, credential_id=hook.webhook_url_credential_id
        )
        if not cred:
            continue
        url = cred.get("webhook_url") or cred.get("url")
        if not url:
            continue
        ok = client.sync_send(
            webhook_url=url,
            payload=_to_slack_payload(n, hook.channel),
        )
        if ok:
            hook.last_delivered_at = datetime.now(timezone.utc)
            hook.last_error = None
        else:
            hook.status = "error"
            hook.last_error = "non-2xx"
        n.delivered_slack = ok or n.delivered_slack


def _to_slack_payload(n: Notification, channel: str | None) -> dict[str, Any]:
    severity_to_emoji = {
        "info": "\U0001F7E2",
        "success": "\u2705",
        "warning": "\u26A0\uFE0F",
        "error": "\U0001F534",
    }
    emoji = severity_to_emoji.get(n.severity, "\U0001F7E2")
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{n.title}*",
            },
        }
    ]
    if n.body:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": n.body[:1500]},
            }
        )
    if n.target_type and n.target_id:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"target: `{n.target_type}:{n.target_id}`",
                    }
                ],
            }
        )
    payload: dict[str, Any] = {
        "text": f"{emoji} {n.title}",
        "blocks": blocks,
    }
    if channel:
        payload["channel"] = channel
    return payload


__all__ = ["publish"]
