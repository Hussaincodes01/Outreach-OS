"""Phase 4 — Replies API (read-only list) + inbound webhook."""
from __future__ import annotations

import hashlib
import hmac
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.config import get_settings
from outreach_os.core.db import session_scope
from outreach_os.core.rate_limit import RateLimitDecision, check_and_consume_ip
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.schemas.phase4 import (
    REPLY_CLASSIFICATIONS,
    ReplyIngestIn,
    ReplyOut,
    ReplyPage,
)
from outreach_os.services.reply_service import ReplyService

log = logging.getLogger(__name__)

router = APIRouter(prefix="/replies", tags=["replies"])


def _rate_limit_webhook(request: Request) -> RateLimitDecision:
    """Check rate limit for webhook by client IP."""
    client_ip = request.client.host if request.client else "unknown"
    return check_and_consume_ip(client_ip, "webhook")


def _raise_429(decision: RateLimitDecision) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Rate limit exceeded. Try again in {decision.retry_after_seconds}s.",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


def _to_out(r) -> ReplyOut:
    return ReplyOut(
        id=r.id,
        created_at=r.created_at,
        tenant_id=r.tenant_id,
        send_id=r.send_id,
        message_id_header=r.message_id_header,
        from_email=r.from_email,
        from_name=r.from_name,
        subject=r.subject,
        body_text=r.body_text,
        received_at=r.received_at,
        classification=r.classification,
        classification_confidence=(
            float(r.classification_confidence) if r.classification_confidence is not None else None
        ),
        classified_at=r.classified_at,
    )


@router.get("", response_model=ReplyPage)
async def list_replies(
    run_id: uuid.UUID | None = None,
    classification: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> ReplyPage:
    if classification is not None and classification not in REPLY_CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail=f"invalid classification: {classification!r}")
    svc = ReplyService(db)
    items, total = await svc.list_replies(
        tenant_id=user.tenant_id,
        run_id=run_id,
        classification=classification,
        limit=limit,
        offset=offset,
    )
    return ReplyPage(
        items=[_to_out(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- Inbound webhook (no auth — signed via HMAC) ---

webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhook_router.post(
    "/inbound-email",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict,
)
async def inbound_email(
    payload: ReplyIngestIn,
    request: Request,
) -> dict:
    """Receive an inbound email reply (Gmail Pub/Sub, SES SNS, SendGrid).

    The body is HMAC-SHA256 signed with `INBOUND_WEBHOOK_SECRET` and
    sent in the `X-Outreach-Signature` header. We look up the tenant
    by matching the In-Reply-To Message-ID to an existing Send.

    Returns 202 even when the reply can't be matched (we'd rather
    silently drop than 500 the upstream webhook).
    """
    settings = get_settings()
    if not settings.inbound_webhook_secret:
        raise HTTPException(status_code=500, detail="INBOUND_WEBHOOK_SECRET not configured")

    # Rate limit: 100 webhook calls/min per IP
    decision = _rate_limit_webhook(request)
    if not decision.allowed:
        _raise_429(decision)

    sig = request.headers.get("X-Outreach-Signature", "")
    raw = (await request.body()).decode("utf-8")
    expected = hmac.new(
        settings.inbound_webhook_secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=401, detail="invalid signature")

    # Find the send by In-Reply-To or References.
    # The webhook doesn't tell us which tenant — we search across all.
    matched_send = await _find_send_across_tenants(
        message_id=payload.in_reply_to or "",
        references=payload.references or "",
        to_email_hint=payload.from_email,
    )
    if matched_send is None:
        return {"matched": False}
    tenant_id, send_id = matched_send
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tenant_id))
        svc = ReplyService(session)
        reply = await svc.ingest(tenant_id=tenant_id, data=payload)
    return {
        "matched": True,
        "tenant_id": str(tenant_id),
        "send_id": str(send_id),
        "reply_id": str(reply.id) if reply else None,
    }


async def _find_send_across_tenants(
    *, message_id: str, references: str, to_email_hint: str
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Search every active tenant for a Send whose Message-ID matches.

    We have to be careful not to leak rows across tenants. The app
    user (no superuser) only sees rows for the current tenant GUC,
    so we iterate one tenant at a time.
    """
    candidates: list[str] = []
    if message_id:
        candidates.append(message_id)
    if references:
        candidates.extend(references.split())
    if not candidates:
        return None
    from outreach_os.core.db import session_scope as _ss
    from outreach_os.domain.models.send import Send
    from outreach_os.domain.models.tenant import Tenant
    from sqlalchemy import select

    async with _ss() as session:
        tenants = (await session.execute(
            select(Tenant.id).where(Tenant.status == "active")
        )).scalars().all()
    for tid in tenants:
        async with _ss() as session:
            await set_tenant_for_session(session, str(tid))
            row = (await session.execute(
                select(Send).where(Send.message_id_header.in_(candidates)).limit(1)
            )).scalar_one_or_none()
            if row is not None:
                return tid, row.id
    return None
