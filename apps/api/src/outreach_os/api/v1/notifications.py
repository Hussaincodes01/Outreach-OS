"""Notification read API.

- GET    /v1/notifications                  \u2014 list (paginated, filterable by event_key + read/unread).
- GET    /v1/notifications/unread_count     \u2014 cheap count for the badge in the sidebar.
- POST   /v1/notifications/mark_read        \u2014 bulk mark.
- GET    /v1/notifications/events           \u2014 master list of event_keys (for the settings UI).
- WS     /v1/ws/notifications               \u2014 per-tenant real-time channel.

WebSocket auth: clients pass the same JWT they use for HTTP, but in a
query parameter (`?token=...`). Browsers can't set headers on the
WebSocket handshake, so the query-string path is the only practical
option. We validate the token + tenant context the same way we do for
the HTTP auth dependency.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.auth import TokenError, decode_token
from outreach_os.core.config import get_settings
from outreach_os.core.ws_manager import get_ws_manager
from outreach_os.domain.models.notification import Notification
from outreach_os.domain.schemas.phase6 import (
    NotificationMarkRead,
    NotificationOut,
    NotificationPage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        event_key=n.event_key,
        severity=n.severity,
        title=n.title,
        body=n.body,
        target_type=n.target_type,
        target_id=n.target_id,
        payload=n.payload,
        read_at=n.read_at,
        delivered_in_app=n.delivered_in_app,
        delivered_email=n.delivered_email,
        delivered_slack=n.delivered_slack,
        created_at=n.created_at,
    )


@router.get("", response_model=NotificationPage)
async def list_notifications(
    event_key: str | None = None,
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> NotificationPage:
    base = select(Notification)
    count_base = select(func.count()).select_from(Notification)
    unread_base = select(func.count()).select_from(Notification).where(Notification.read_at.is_(None))
    if event_key:
        base = base.where(Notification.event_key == event_key)
        count_base = count_base.where(Notification.event_key == event_key)
        unread_base = unread_base.where(Notification.event_key == event_key)
    if unread_only:
        base = base.where(Notification.read_at.is_(None))

    total = (await db.execute(count_base)).scalar_one()
    unread = (await db.execute(unread_base)).scalar_one()
    rows = (
        (
            await db.execute(
                base.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return NotificationPage(
        items=[_to_out(r) for r in rows],
        total=total,
        unread=unread,
        limit=limit,
        offset=offset,
    )


@router.get("/unread_count")
async def unread_count(
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> dict[str, int]:
    n = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.read_at.is_(None))
        )
    ).scalar_one()
    return {"unread": n}


@router.get("/events")
async def list_event_keys() -> dict[str, list[str]]:
    """Master list of all event keys. The UI uses this to render the
    preference matrix in /settings."""
    return {"events": list(get_settings().notification_event_keys)}


@router.post("/mark_read", response_model=dict)
async def mark_read(
    body: NotificationMarkRead,
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> dict[str, int]:
    if not body.ids:
        return {"updated": 0}
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(Notification)
        .where(Notification.id.in_(body.ids), Notification.read_at.is_(None))
        .values(read_at=now)
        .returning(Notification.id)
    )
    return {"updated": len(result.scalars().all())}


# ---------- WebSocket ----------


@router.websocket("/ws")
async def notifications_ws(
    websocket: WebSocket,
    token: Annotated[str | None, Query()] = None,
) -> None:
    """Per-tenant live notification feed.

    Query: ?token=<jwt>

    The token must include a `tid` claim matching a tenant the user
    belongs to. We don't set the RLS GUC on the WebSocket path \u2014 the
    channel is just a fan-out; no DB reads happen here.
    """
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    tid_str = payload.get("tid")
    if not tid_str:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        tenant_id = uuid.UUID(tid_str)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    manager = get_ws_manager()
    await manager.connect(tenant_id, websocket)
    try:
        # Send a hello so the client knows it's authenticated + connected.
        await websocket.send_json({"event_key": "ws.connected", "title": "connected"})
        while True:
            # We don't expect any inbound messages, but the receive is
            # needed to detect client-side disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning("ws: unexpected error: %s", e)
    finally:
        await manager.disconnect(tenant_id, websocket)


__all__ = ["router"]
