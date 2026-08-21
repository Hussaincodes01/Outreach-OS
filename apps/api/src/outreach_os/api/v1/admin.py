"""Platform admin console — the operator's view of their customers.

Access is gated on `app_user.is_platform_admin`, which no API can set (see
migration 0018). A tenant owner is an admin *of their workspace*; that must
never imply visibility of anyone else's.

RLS is respected rather than bypassed. The customer list is built from the
`tenant` and `plan` tables, which hold no tenant-private content and are
therefore not RLS-protected. Anything private — a customer's leads, users or
subscription row — is read only after binding that specific tenant, so the
console cannot accidentally spill one customer's data into another's row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_admin_db, require_platform_admin
from outreach_os.core.audit import write_audit_event
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.plan import Plan
from outreach_os.domain.models.subscription import Subscription
from outreach_os.domain.models.tenant import Tenant
from outreach_os.domain.models.user import AppUser
from outreach_os.domain.schemas.admin import (
    AdminCustomerOut,
    AdminCustomerPage,
    AdminStatsOut,
    AdminTenantStatusIn,
)

router = APIRouter(prefix="/admin", tags=["admin"])

_TENANT_STATUSES = ("active", "suspended", "cancelled")


async def _subscriptions_for(
    db: AsyncSession, tenant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[Subscription, Plan]]:
    """Latest subscription per tenant.

    `subscription` is RLS-protected, so each tenant is bound in turn rather
    than the policy being disabled. That costs a query per customer on one
    page of results — worth paying to keep the isolation guarantee whole.
    """
    out: dict[uuid.UUID, tuple[Subscription, Plan]] = {}
    for tid in tenant_ids:
        await set_tenant_for_session(db, str(tid))
        row = (
            await db.execute(
                select(Subscription, Plan)
                .join(Plan, Plan.id == Subscription.plan_id)
                .where(Subscription.tenant_id == tid)
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
        ).first()
        if row is not None:
            out[tid] = (row[0], row[1])
    return out


async def _counts_for(
    db: AsyncSession, tenant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """(user_count, lead_count) per tenant, read under that tenant's RLS."""
    out: dict[uuid.UUID, tuple[int, int]] = {}
    for tid in tenant_ids:
        await set_tenant_for_session(db, str(tid))
        users = int(
            (
                await db.execute(
                    select(func.count(AppUser.id)).where(AppUser.tenant_id == tid)
                )
            ).scalar_one()
            or 0
        )
        leads = int(
            (
                await db.execute(
                    select(func.count(Lead.id)).where(Lead.tenant_id == tid)
                )
            ).scalar_one()
            or 0
        )
        out[tid] = (users, leads)
    return out


def _to_out(
    tenant: Tenant,
    counts: tuple[int, int],
    sub_plan: tuple[Subscription, Plan] | None,
) -> AdminCustomerOut:
    sub = sub_plan[0] if sub_plan else None
    plan = sub_plan[1] if sub_plan else None
    return AdminCustomerOut(
        tenant_id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        plan=tenant.plan,
        user_count=counts[0],
        lead_count=counts[1],
        created_at=tenant.created_at,
        month_usage_sends=tenant.month_usage_sends,
        month_usage_leads=tenant.month_usage_leads,
        month_usage_llm_tokens=tenant.month_usage_llm_tokens,
        subscription_status=sub.status if sub else None,
        subscription_provider=sub.provider if sub else None,
        current_period_end=sub.current_period_end if sub else None,
        cancel_at_period_end=bool(sub.cancel_at_period_end) if sub else False,
        monthly_price_cents=plan.monthly_price_cents if plan else 0,
    )


@router.get("/customers", response_model=AdminCustomerPage)
async def list_customers(
    q: str | None = Query(default=None, description="Match name or slug"),
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: AuthContext = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_admin_db),
) -> AdminCustomerPage:
    """Every customer workspace, with plan, usage and subscription state."""
    base = select(Tenant)
    count_q = select(func.count(Tenant.id))
    if q:
        pattern = f"%{q.lower()}%"
        cond = or_(
            func.lower(Tenant.name).like(pattern),
            func.lower(Tenant.slug).like(pattern),
        )
        base = base.where(cond)
        count_q = count_q.where(cond)
    if status_:
        base = base.where(Tenant.status == status_)
        count_q = count_q.where(Tenant.status == status_)

    total = int((await db.execute(count_q)).scalar_one() or 0)
    tenants = list(
        (
            await db.execute(
                base.order_by(Tenant.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    if not tenants:
        return AdminCustomerPage(items=[], total=total, limit=limit, offset=offset)

    tenant_ids = [t.id for t in tenants]
    subs = await _subscriptions_for(db, tenant_ids)
    counts = await _counts_for(db, tenant_ids)
    return AdminCustomerPage(
        items=[_to_out(t, counts.get(t.id, (0, 0)), subs.get(t.id)) for t in tenants],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=AdminStatsOut)
async def admin_stats(
    admin: AuthContext = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_admin_db),
) -> AdminStatsOut:
    """Headline numbers across all customers."""
    tenants = list((await db.execute(select(Tenant))).scalars().all())

    by_plan: dict[str, int] = {}
    for t in tenants:
        by_plan[t.plan] = by_plan.get(t.plan, 0) + 1

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    signups = len(
        [t for t in tenants if t.created_at is not None and t.created_at >= cutoff]
    )

    subs = await _subscriptions_for(db, [t.id for t in tenants])
    paying = 0
    mrr = 0
    for sub, plan in subs.values():
        # Only subscriptions actually being billed count toward the total.
        if sub.status in ("active", "trialing") and plan.monthly_price_cents > 0:
            paying += 1
            mrr += plan.monthly_price_cents

    return AdminStatsOut(
        total_customers=len(tenants),
        active_customers=sum(1 for t in tenants if t.status == "active"),
        suspended_customers=sum(1 for t in tenants if t.status == "suspended"),
        paying_customers=paying,
        mrr_cents=mrr,
        customers_by_plan=by_plan,
        signups_last_30d=signups,
        total_leads=sum(t.month_usage_leads for t in tenants),
        total_sends_this_month=sum(t.month_usage_sends for t in tenants),
    )


@router.patch("/customers/{tenant_id}/status", response_model=AdminCustomerOut)
async def set_customer_status(
    tenant_id: uuid.UUID,
    body: AdminTenantStatusIn,
    admin: AuthContext = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_admin_db),
) -> AdminCustomerOut:
    """Suspend or reactivate a workspace.

    Written to the acting admin's own audit log, so operator actions on
    customer accounts are as traceable as customer actions.
    """
    if body.status not in _TENANT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {', '.join(sorted(_TENANT_STATUSES))}",
        )
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="customer not found")

    previous = tenant.status
    tenant.status = body.status
    await db.flush()

    await set_tenant_for_session(db, str(admin.tenant_id))
    await write_audit_event(
        db,
        action="admin.tenant_status_changed",
        target_type="tenant",
        target_id=tenant_id,
        actor_kind="user",
        actor_id=admin.user_id,
        payload={"from": previous, "to": body.status, "slug": tenant.slug},
    )

    subs = await _subscriptions_for(db, [tenant_id])
    counts = await _counts_for(db, [tenant_id])
    return _to_out(tenant, counts.get(tenant_id, (0, 0)), subs.get(tenant_id))


__all__ = ["router"]
