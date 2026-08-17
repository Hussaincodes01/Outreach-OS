"""Phase 7 \u2014 billing + plan API.

- GET    /v1/billing/plans                    \u2014 list public plans.
- GET    /v1/billing/subscription             \u2014 active sub + plan.
- GET    /v1/billing/usage                    \u2014 current usage vs cap.
- POST   /v1/billing/checkout                 \u2014 start Stripe checkout.
- POST   /v1/billing/portal                   \u2014 open the billing portal.
- GET    /v1/billing/portal/redirect          \u2014 consume a portal token, 302.
- GET    /v1/billing/stub/complete            \u2014 dev-only checkout completion.
- POST   /v1/billing/webhook/stripe           \u2014 real Stripe webhook.
- POST   /v1/billing/portal/internal          \u2014 internal/dev fake-portal.

Plan-gated features are enforced *inside* the relevant services (send,
scraping, crm). The router here is read-mostly; the writes are
limited to checkout + portal start.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_db, get_scoped_db
from outreach_os.core.billing_client import get_billing_client
from outreach_os.core.config import get_settings
from outreach_os.core.db import session_scope
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.billing_portal_token import BillingPortalToken
from outreach_os.domain.models.plan import Plan
from outreach_os.domain.models.subscription import Subscription
from outreach_os.domain.schemas.phase7 import (
    CheckoutOut,
    CheckoutRequest,
    PlanListOut,
    PlanOut,
    PortalOut,
    PortalRequest,
    StripeWebhookAck,
    SubscriptionOut,
    UsageSummaryOut,
)
from outreach_os.services import billing_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


# ---------- public plans ----------


@router.get("/plans/public", response_model=PlanListOut)
async def list_plans_public(db: AsyncSession = Depends(get_db)) -> PlanListOut:
    """Plan definitions, without authentication.

    The marketing page needs these before anyone has an account, and pricing
    is not secret. Safe to serve unscoped: `plan` is one of the few tables
    with no RLS policy because it holds no tenant data.
    """
    plans = await billing_service.list_plans(db)
    return PlanListOut(items=[PlanOut.model_validate(p) for p in plans])


@router.get("/plans", response_model=PlanListOut)
async def list_plans(
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> PlanListOut:
    plans = await billing_service.list_plans(db)
    return PlanListOut(items=[PlanOut.model_validate(p) for p in plans])


# ---------- active subscription ----------


@router.get("/subscription", response_model=SubscriptionOut | None)
async def get_subscription(
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SubscriptionOut | None:
    sub = await billing_service.active_subscription(db, tenant_id=_user.tenant_id)
    if sub is None:
        return None
    plan = await db.get(Plan, sub.plan_id)
    if plan is None:
        return None
    return SubscriptionOut(
        id=sub.id,
        plan=PlanOut.model_validate(plan),
        status=sub.status,
        provider=sub.provider,
        provider_customer_id=sub.provider_customer_id,
        provider_subscription_id=sub.provider_subscription_id,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
        canceled_at=sub.canceled_at,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
    )


# ---------- usage ----------


@router.get("/usage", response_model=UsageSummaryOut)
async def get_usage(
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> UsageSummaryOut:
    s = await billing_service.usage_summary(db, tenant_id=_user.tenant_id)
    return UsageSummaryOut(**s)


# ---------- checkout ----------


@router.post("/checkout", response_model=CheckoutOut)
async def start_checkout(
    body: CheckoutRequest,
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CheckoutOut:
    settings = get_settings()
    success = body.success_url or f"{settings.public_base_url}/settings?checkout=success"
    cancel = body.cancel_url or f"{settings.public_base_url}/settings?checkout=cancel"
    try:
        url = await billing_service.start_checkout(
            db,
            tenant_id=_user.tenant_id,
            plan_code=body.plan_code,
            success_url=success,
            cancel_url=cancel,
        )
    except billing_service.PlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CheckoutOut(checkout_url=url, provider=settings.billing_provider)


# ---------- portal ----------


@router.post("/portal", response_model=PortalOut)
async def start_portal(
    body: PortalRequest,
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> PortalOut:
    settings = get_settings()
    return_url = body.return_url or f"{settings.public_base_url}/settings"
    out = await billing_service.start_portal(
        db,
        tenant_id=_user.tenant_id,
        user_id=_user.user_id,
        return_url=return_url,
    )
    return PortalOut(**out)


@router.get("/portal/redirect")
async def portal_redirect(token: str) -> RedirectResponse:
    """Validate a one-shot portal token and 302 to the portal URL.

    The token was issued by `POST /portal`; consuming it prevents
    replay. We don't gate on user identity here — the token is the
    capability.
    """
    if not token:
        raise HTTPException(status_code=400, detail="missing token")
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        # billing_portal_token has no RLS — the token IS the capability.
        row = (
            await session.execute(
                select(BillingPortalToken).where(
                    BillingPortalToken.token == token,
                    BillingPortalToken.consumed_at.is_(None),
                    BillingPortalToken.expires_at > now,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="token invalid or expired")
        row.consumed_at = now
        # Now we know which tenant this is for; set RLS and look up
        # the active subscription to build a portal session.
        await set_tenant_for_session(session, str(row.tenant_id))
        sub = (
            await session.execute(
                select(Subscription).where(
                    Subscription.tenant_id == row.tenant_id,
                    Subscription.status.in_(("active", "trialing", "past_due")),
                )
            )
        ).scalar_one_or_none()
        if sub is None or sub.provider_customer_id is None:
            raise HTTPException(status_code=404, detail="no subscription")
        url = get_billing_client().create_portal_session(
            customer_id=sub.provider_customer_id,
            return_url=get_settings().public_base_url + "/settings",
        )
    return RedirectResponse(url=url, status_code=302)


# ---------- stub checkout completion (dev only) ----------


@router.get("/stub/complete")
async def stub_complete(
    session: str,
    plan: str = "starter",
    db: AsyncSession = Depends(get_scoped_db),
) -> RedirectResponse:
    """Dev-only endpoint: completes a stub checkout session and
    applies a subscription event. In production this route 404s.
    """
    if get_settings().billing_provider != "stub":
        raise HTTPException(status_code=404, detail="not found")
    client = get_billing_client()
    info = getattr(client, "sessions", {}).get(session)
    if info is None:
        raise HTTPException(status_code=404, detail="session not found")
    # We don't know the tenant from the stub; the success_url is
    # expected to carry it. The dashboard's success handler hits
    # /v1/billing/webhook/stub instead \u2014 this is just the
    # direct-completion path for tests.
    raise HTTPException(
        status_code=400,
        detail="stub checkout completion requires /v1/billing/webhook/stub",
    )


@router.post("/webhook/stub", response_model=StripeWebhookAck)
async def stub_webhook(
    request: Request,
) -> StripeWebhookAck:
    """Dev-only webhook that applies a subscription event.

    Body: {"tenant_id": "...", "plan_code": "starter", "status": "active"}
    """
    if get_settings().billing_provider != "stub":
        raise HTTPException(status_code=404, detail="not found")
    import json
    body = json.loads((await request.body()).decode("utf-8"))
    tenant_id = uuid.UUID(body["tenant_id"])
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tenant_id))
        await billing_service.apply_subscription_event(
            session,
            tenant_id=tenant_id,
            plan_code=body["plan_code"],
            provider="stub",
            provider_customer_id=body.get("customer_id"),
            provider_subscription_id=body.get("subscription_id"),
            status=body.get("status", "active"),
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc).replace(
                day=28
            ) + (
                datetime.now(timezone.utc).replace(day=1) - datetime.now(timezone.utc)
            ),
        )
    return StripeWebhookAck(received=True, processed=True)


# ---------- real stripe webhook ----------


@router.post("/webhook/stripe", response_model=StripeWebhookAck)
async def stripe_webhook(request: Request) -> StripeWebhookAck:
    """Process a real Stripe webhook.

    We trust the verified payload; signature check is in
    `billing_client.verify_webhook_signature`. Supported events:
      - checkout.session.completed
      - customer.subscription.created
      - customer.subscription.updated
      - customer.subscription.deleted
    """
    raw = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = get_billing_client().verify_webhook_signature(
            payload=raw, signature=sig
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"signature: {e}") from e

    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})
    if event_type in (
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        # Resolve plan_code from the line items' price lookup_key.
        plan_code = "starter"
        items = data.get("line_items", {}).get("data", [])
        for item in items:
            price = item.get("price", {})
            lk = price.get("lookup_key", "")
            if lk.startswith("plan_"):
                plan_code = lk.removeprefix("plan_")
                break
        # Tenant id is stored in metadata when we create the session.
        tenant_str = data.get("metadata", {}).get("tenant_id")
        if not tenant_str:
            return StripeWebhookAck(
                received=True, processed=False, message="no tenant_id in metadata"
            )
        tenant_id = uuid.UUID(tenant_str)
        status = data.get("status", "active")
        # `current_period_start` / `current_period_end` come from the
        # subscription object, not the session object.
        cps = data.get("current_period_start")
        cpe = data.get("current_period_end")
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        cps_dt = _dt.fromtimestamp(cps, _tz.utc) if cps else None
        cpe_dt = _dt.fromtimestamp(cpe, _tz.utc) if cpe else None
        async with session_scope() as session:
            await set_tenant_for_session(session, str(tenant_id))
            await billing_service.apply_subscription_event(
                session,
                tenant_id=tenant_id,
                plan_code=plan_code,
                provider="stripe",
                provider_customer_id=data.get("customer"),
                provider_subscription_id=data.get("id"),
                status=status,
                current_period_start=cps_dt,
                current_period_end=cpe_dt,
            )
        return StripeWebhookAck(received=True, processed=True)
    if event_type == "customer.subscription.deleted":
        sub_id = data.get("id")
        async with session_scope() as session:
            row = (
                await session.execute(
                    select(Subscription).where(
                        Subscription.provider_subscription_id == sub_id
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                row.status = "canceled"
                row.canceled_at = datetime.now(timezone.utc)
        return StripeWebhookAck(received=True, processed=True)
    return StripeWebhookAck(received=True, processed=False, message=f"unhandled {event_type}")


__all__ = ["router"]
