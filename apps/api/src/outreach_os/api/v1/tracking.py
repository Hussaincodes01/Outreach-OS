"""Tracking endpoints (no auth) — open pixel, click redirect, unsubscribe.

These endpoints are intentionally unauthenticated because they're hit
by external email clients (image loaders) and link clickers. The
tracking_id (the send UUID) is a public random identifier; we record
the hit but never expose tenant data in the response.

The 1x1 transparent PNG and the redirect are returned with proper
cache-busting headers so the browser actually fires the request.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from outreach_os.core.db import session_scope
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.send import Send
from outreach_os.domain.models.suppression import Suppression
from outreach_os.domain.models.tracking_event import TrackingEvent

log = logging.getLogger(__name__)

router = APIRouter(prefix="/t", tags=["tracking"])

# 1x1 transparent PNG.
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfe\xa3\x9a\xfa\xfa\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _record_event(
    send: Send, event_type: str, url: str | None, request: Request
) -> None:
    async with session_scope() as session:
        await set_tenant_for_session(session, str(send.tenant_id))
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")
        session.add(
            TrackingEvent(
                tenant_id=send.tenant_id,
                send_id=send.id,
                event_type=event_type,
                url=url,
                ip=ip,
                user_agent=ua[:500] if ua else None,
            )
        )
        # Promote the send's opened_at / clicked_at for the API list.
        if event_type == "open" and send.opened_at is None:
            from datetime import datetime
            s = (
                await session.execute(
                    select(Send).where(Send.id == send.id)
                )
            ).scalar_one()
            s.opened_at = datetime.utcnow()
        elif event_type == "click" and send.clicked_at is None:
            from datetime import datetime
            s = (
                await session.execute(
                    select(Send).where(Send.id == send.id)
                )
            ).scalar_one()
            s.clicked_at = datetime.utcnow()


async def _find_send(send_id: uuid.UUID) -> Send | None:
    # We don't know the tenant, so we have to iterate.
    from outreach_os.core.db import session_scope as _ss
    from outreach_os.domain.models.tenant import Tenant
    async with _ss() as session:
        tenants = (await session.execute(
            select(Tenant.id).where(Tenant.status == "active")
        )).scalars().all()
    for tid in tenants:
        async with _ss() as session:
            await set_tenant_for_session(session, str(tid))
            row = (await session.execute(
                select(Send).where(Send.id == send_id)
            )).scalar_one_or_none()
            if row is not None:
                return row
    return None


@router.get("/open/{send_id}.png")
async def open_pixel(send_id: uuid.UUID, request: Request) -> Response:
    """Returns a 1x1 transparent PNG and records an 'open' event."""
    send = await _find_send(send_id)
    if send is not None:
        try:
            await _record_event(send, "open", None, request)
        except Exception as exc:
            log.warning("failed to record open: %s", exc)
    return Response(
        content=_PNG_BYTES,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/click/{send_id}")
async def click_redirect(
    send_id: uuid.UUID,
    request: Request,
    url: str = Query(...),
) -> RedirectResponse:
    """Redirects to the original URL and records a 'click' event."""
    send = await _find_send(send_id)
    if send is not None:
        try:
            await _record_event(send, "click", url, request)
        except Exception as exc:
            log.warning("failed to record click: %s", exc)
    return RedirectResponse(url=url, status_code=302)


@router.get("/unsubscribe")
async def unsubscribe(
    request: Request,
    email: str = Query(...),
    tenant: str = Query(...),
) -> Response:
    """Public one-click unsubscribe. Adds the email to the suppression
    list for the given tenant. Always returns 200 — the unsubscribe
    link in the email must never fail."""
    from outreach_os.core.db import session_scope as _ss
    try:
        tenant_uuid = uuid.UUID(tenant)
    except ValueError:
        return Response("OK", media_type="text/plain")
    try:
        async with _ss() as session:
            await set_tenant_for_session(session, tenant)
            existing = (await session.execute(
                select(Suppression).where(
                    Suppression.tenant_id == tenant_uuid,
                    Suppression.email == email.lower(),
                )
            )).scalar_one_or_none()
            if existing is None:
                session.add(
                    Suppression(
                        tenant_id=tenant_uuid,
                        email=email.lower(),
                        reason="unsubscribe",
                        source="one-click",
                    )
                )
    except Exception as exc:
        log.warning("unsubscribe failed: %s", exc)
    return Response(
        content="You have been unsubscribed. You will not receive further emails from us.",
        media_type="text/plain",
    )
