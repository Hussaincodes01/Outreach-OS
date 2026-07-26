"""Billing service \u2014 plan lookup, subscription state, usage gates.

The public surface is small:
- `current_plan(tenant_id)` -> Plan | None (None = free)
- `active_subscription(tenant_id)` -> Subscription | None
- `start_checkout(tenant_id, plan_code, success_url, cancel_url)` -> URL
- `apply_subscription_event(...)` -> updated Subscription (called by webhook)
- `record_usage(tenant_id, metric, qty, source, source_id)` -> None
- `check_within_limits(tenant_id, metric, n)` -> bool  (raises if over)
- `usage_summary(tenant_id)` -> UsageSummaryOut

The service never blocks the API request: `check_within_limits`
raises `BillingLimitExceededError`, which the API layer translates to
HTTP 402.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.billing_client import get_billing_client
from outreach_os.domain.models.plan import Plan
from outreach_os.domain.models.subscription import Subscription
from outreach_os.domain.models.tenant import Tenant
from outreach_os.domain.models.usage_event import UsageEvent

log = logging.getLogger(__name__)


class BillingError(Exception):
    """Base billing exception."""


class BillingLimitExceededError(BillingError):
    def __init__(self, *, metric: str, used: int, cap: int) -> None:
        super().__init__(f"{metric}: used {used} of cap {cap}")
        self.metric = metric
        self.used = used
        self.cap = cap


class PlanNotFoundError(BillingError):
    pass


# ---------- plan / subscription read paths ----------


async def list_plans(session: AsyncSession) -> list[Plan]:
    return list(
        (
            await session.execute(
                select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.display_order)
            )
        ).scalars().all()
    )


async def get_plan_by_code(session: AsyncSession, code: str) -> Plan | None:
    return (
        await session.execute(select(Plan).where(Plan.code == code))
    ).scalar_one_or_none()


async def active_subscription(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> Subscription | None:
    return (
        await session.execute(
            select(Subscription).where(
                Subscription.tenant_id == tenant_id,
                Subscription.status.in_(("active", "trialing", "past_due")),
            )
        )
    ).scalar_one_or_none()


def implicit_free_plan() -> dict[str, int | bool]:
    """Limits applied when a tenant has no active subscription."""
    return {
        "monthly_send_cap": 50,
        "monthly_lead_cap": 100,
        "monthly_llm_token_cap": 20_000,
        "crm_sync_enabled": False,
        "slack_notifications_enabled": False,
        "email_digest_enabled": False,
        "max_team_seats": 1,
        "max_mailboxes": 1,
    }


async def effective_plan(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> Plan:
    sub = await active_subscription(session, tenant_id=tenant_id)
    if sub is not None:
        plan = await session.get(Plan, sub.plan_id)
        if plan is not None and plan.is_active:
            return plan
    # Fall back to a free-plan shim. The starter plan is the closest match.
    starter = await get_plan_by_code(session, "starter")
    if starter is not None:
        return starter
    raise PlanNotFoundError("no starter plan configured")


# ---------- usage gates ----------


async def check_within_limits(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    metric: str,
    n: int = 1,
) -> None:
    """Raise BillingLimitExceededError if recording `n` more units of `metric`
    would push the tenant over their plan's monthly cap.

    Called *before* performing the work. If the work succeeds, the
    caller should then call `record_usage`.
    """
    if n <= 0:
        return
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        return
    plan = await effective_plan(session, tenant_id=tenant_id)
    cap_map = {
        "send": plan.monthly_send_cap,
        "lead_scraped": plan.monthly_lead_cap,
        "llm_token_in": plan.monthly_llm_token_cap,
        "llm_token_out": plan.monthly_llm_token_cap,
    }
    used_map = {
        "send": tenant.month_usage_sends,
        "lead_scraped": tenant.month_usage_leads,
        "llm_token_in": tenant.month_usage_llm_tokens,
        "llm_token_out": tenant.month_usage_llm_tokens,
    }
    if metric not in cap_map:
        return  # unknown metric: don't gate
    cap = cap_map[metric]
    used = used_map[metric]
    if used + n > cap:
        raise BillingLimitExceededError(metric=metric, used=used, cap=cap)


async def record_usage(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    metric: str,
    quantity: int = 1,
    source: str | None = None,
    source_id: uuid.UUID | None = None,
) -> None:
    """Append a usage event + bump the tenant rollup counter.

    Safe to call after the work succeeded. Failures here are logged
    but never raised \u2014 metering is best-effort, not load-bearing.
    """
    if quantity <= 0:
        return
    try:
        session.add(
            UsageEvent(
                tenant_id=tenant_id,
                metric=metric,
                quantity=quantity,
                source=source,
                source_id=source_id,
            )
        )
        tenant = await session.get(Tenant, tenant_id)
        if tenant is not None:
            if metric == "send":
                tenant.month_usage_sends += quantity
            elif metric == "lead_scraped":
                tenant.month_usage_leads += quantity
            elif metric in ("llm_token_in", "llm_token_out"):
                tenant.month_usage_llm_tokens += quantity
        await session.flush()
    except Exception:
        log.exception("record_usage failed tenant=%s metric=%s", tenant_id, metric)


async def usage_summary(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> dict[str, Any]:
    tenant = await session.get(Tenant, tenant_id)
    plan = await effective_plan(session, tenant_id=tenant_id)
    if tenant is None:
        return {
            "sends_used": 0, "sends_cap": plan.monthly_send_cap,
            "leads_used": 0, "leads_cap": plan.monthly_lead_cap,
            "llm_tokens_used": 0, "llm_tokens_cap": plan.monthly_llm_token_cap,
            "reset_at": datetime.now(timezone.utc),
            "over_sends": False, "over_leads": False, "over_llm_tokens": False,
        }
    return {
        "sends_used": tenant.month_usage_sends,
        "sends_cap": plan.monthly_send_cap,
        "leads_used": tenant.month_usage_leads,
        "leads_cap": plan.monthly_lead_cap,
        "llm_tokens_used": tenant.month_usage_llm_tokens,
        "llm_tokens_cap": plan.monthly_llm_token_cap,
        "reset_at": tenant.month_usage_reset_at,
        "over_sends": tenant.month_usage_sends > plan.monthly_send_cap,
        "over_leads": tenant.month_usage_leads > plan.monthly_lead_cap,
        "over_llm_tokens": tenant.month_usage_llm_tokens > plan.monthly_llm_token_cap,
    }


# ---------- checkout / portal / webhook ----------


async def start_checkout(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    plan_code: str,
    success_url: str,
    cancel_url: str,
) -> str:
    plan = await get_plan_by_code(session, plan_code)
    if plan is None:
        raise PlanNotFoundError(f"plan {plan_code!r} not found")
    sub = await active_subscription(session, tenant_id=tenant_id)
    client = get_billing_client()
    return client.create_checkout_session(
        customer_id=sub.provider_customer_id if sub else None,
        price_lookup_key=f"plan_{plan_code}",
        success_url=success_url,
        cancel_url=cancel_url,
    )


async def start_portal(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    return_url: str,
) -> dict[str, Any]:
    """Return a single-use bearer token + portal URL.

    The dashboard hits /v1/billing/portal?token=... which validates
    the token, marks it consumed, and redirects to the Stripe
    portal URL.
    """
    from outreach_os.domain.models.billing_portal_token import BillingPortalToken

    sub = await active_subscription(session, tenant_id=tenant_id)
    if sub is None or sub.provider_customer_id is None:
        # Stub/dev fallback: skip the token round-trip and return the
        # portal URL directly.
        client = get_billing_client()
        url = client.create_portal_session(
            customer_id="free-tier", return_url=return_url
        )
        return {
            "portal_url": url,
            "token": None,
            "expires_at": None,
        }
    client = get_billing_client()
    portal_url = client.create_portal_session(
        customer_id=sub.provider_customer_id, return_url=return_url
    )
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    session.add(
        BillingPortalToken(
            tenant_id=tenant_id,
            user_id=user_id,
            token=token,
            expires_at=expires_at,
        )
    )
    await session.flush()
    return {
        "portal_url": portal_url,
        "token": token,
        "expires_at": expires_at,
    }


async def apply_subscription_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    plan_code: str,
    provider: str,
    provider_customer_id: str | None,
    provider_subscription_id: str | None,
    status: str,
    current_period_start: datetime | None,
    current_period_end: datetime | None,
) -> Subscription:
    """Upsert the active subscription row for a tenant.

    Called by:
    - The stub `/v1/billing/stub/complete` endpoint when a test
      "finishes" a checkout.
    - The Stripe webhook handler when a real `customer.subscription.*`
      event arrives.
    """
    plan = await get_plan_by_code(session, plan_code)
    if plan is None:
        raise PlanNotFoundError(f"plan {plan_code!r} not found")
    sub = await active_subscription(session, tenant_id=tenant_id)
    now = datetime.now(timezone.utc)
    if sub is None:
        sub = Subscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            status=status,
            provider=provider,
            provider_customer_id=provider_customer_id,
            provider_subscription_id=provider_subscription_id,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
        )
        session.add(sub)
    else:
        sub.plan_id = plan.id
        sub.status = status
        sub.provider = provider
        sub.provider_customer_id = provider_customer_id
        sub.provider_subscription_id = provider_subscription_id
        sub.current_period_start = current_period_start
        sub.current_period_end = current_period_end
        sub.updated_at = now
    await session.flush()
    # Mirror plan.code onto the tenant row for fast dashboard reads.
    tenant = await session.get(Tenant, tenant_id)
    if tenant is not None:
        tenant.plan = plan_code
    return sub


async def rollup_usage_counters(session: AsyncSession) -> int:
    """Reset month_usage_* counters and recompute from usage_event for
    any tenant whose reset window has rolled over.

    Returns the number of tenants rolled up.
    """
    now = datetime.now(timezone.utc)
    month_start = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    # Tenants whose last reset is before this month.
    rows = (
        await session.execute(
            select(Tenant).where(Tenant.month_usage_reset_at < month_start)
        )
    ).scalars().all()
    count = 0
    for t in rows:
        sends = (
            await session.execute(
                select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                    UsageEvent.tenant_id == t.id,
                    UsageEvent.metric == "send",
                    UsageEvent.created_at >= month_start,
                )
            )
        ).scalar_one()
        leads = (
            await session.execute(
                select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                    UsageEvent.tenant_id == t.id,
                    UsageEvent.metric == "lead_scraped",
                    UsageEvent.created_at >= month_start,
                )
            )
        ).scalar_one()
        toks = (
            await session.execute(
                select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                    UsageEvent.tenant_id == t.id,
                    UsageEvent.metric.in_(("llm_token_in", "llm_token_out")),
                    UsageEvent.created_at >= month_start,
                )
            )
        ).scalar_one()
        t.month_usage_sends = int(sends or 0)
        t.month_usage_leads = int(leads or 0)
        t.month_usage_llm_tokens = int(toks or 0)
        t.month_usage_reset_at = month_start
        count += 1
    return count


__all__ = [
    "BillingError",
    "BillingLimitExceededError",
    "PlanNotFoundError",
    "active_subscription",
    "apply_subscription_event",
    "check_within_limits",
    "effective_plan",
    "get_plan_by_code",
    "implicit_free_plan",
    "list_plans",
    "record_usage",
    "rollup_usage_counters",
    "start_checkout",
    "start_portal",
    "usage_summary",
]
