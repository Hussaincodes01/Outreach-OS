"""Schemas for the platform admin console."""
from __future__ import annotations

import uuid
from datetime import datetime

from outreach_os.domain.schemas.common import ApiModel


class AdminCustomerOut(ApiModel):
    """One customer workspace as the operator sees it."""

    tenant_id: uuid.UUID
    name: str
    slug: str
    status: str
    plan: str
    user_count: int
    lead_count: int
    created_at: datetime
    # Monthly rollups, reset on month_usage_reset_at.
    month_usage_sends: int
    month_usage_leads: int
    month_usage_llm_tokens: int
    # Present only once a subscription exists.
    subscription_status: str | None = None
    subscription_provider: str | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    monthly_price_cents: int = 0


class AdminCustomerPage(ApiModel):
    items: list[AdminCustomerOut]
    total: int
    limit: int
    offset: int


class AdminStatsOut(ApiModel):
    """Headline numbers for the operator's dashboard."""

    total_customers: int
    active_customers: int
    suspended_customers: int
    paying_customers: int
    # Sum of monthly_price_cents across active paid subscriptions. Named
    # plainly: it is a snapshot of list price, not accounting revenue.
    mrr_cents: int
    customers_by_plan: dict[str, int]
    signups_last_30d: int
    total_leads: int
    total_sends_this_month: int


class AdminTenantStatusIn(ApiModel):
    # 'suspended' blocks the workspace; 'active' restores it.
    status: str
