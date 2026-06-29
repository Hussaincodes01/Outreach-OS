"""Pydantic schemas for Phase 7 \u2014 billing + plans.

- PlanOut              \u2014 public plan listing.
- PlanDetail           \u2014 same + limits + features.
- SubscriptionOut      \u2014 active subscription row + plan.
- UsageSummaryOut      \u2014 tenant.month_usage_* + caps.
- CheckoutRequest/Out  \u2014 what to call to start checkout.
- PortalRequest/Out    \u2014 portal token + redirect URL.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------- Plan ----------


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    monthly_price_cents: int
    monthly_send_cap: int
    monthly_lead_cap: int
    monthly_llm_token_cap: int
    crm_sync_enabled: bool
    slack_notifications_enabled: bool
    email_digest_enabled: bool
    max_team_seats: int
    max_mailboxes: int
    display_order: int


class PlanListOut(BaseModel):
    items: list[PlanOut]


# ---------- Subscription ----------


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan: PlanOut
    status: str
    provider: str
    provider_customer_id: str | None
    provider_subscription_id: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    canceled_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ---------- Usage ----------


class UsageSummaryOut(BaseModel):
    sends_used: int
    sends_cap: int
    leads_used: int
    leads_cap: int
    llm_tokens_used: int
    llm_tokens_cap: int
    reset_at: datetime
    over_sends: bool
    over_leads: bool
    over_llm_tokens: bool


# ---------- Checkout ----------


class CheckoutRequest(BaseModel):
    plan_code: Literal["starter", "growth", "scale"] = Field(...)
    success_url: str | None = None
    cancel_url: str | None = None


class CheckoutOut(BaseModel):
    checkout_url: str
    provider: str


# ---------- Portal ----------


class PortalRequest(BaseModel):
    return_url: str | None = None


class PortalOut(BaseModel):
    portal_url: str
    token: str
    expires_at: datetime


# ---------- Webhook (Stripe) ----------


class StripeWebhookAck(BaseModel):
    received: bool
    processed: bool
    message: str | None = None


__all__ = [
    "CheckoutOut",
    "CheckoutRequest",
    "PlanListOut",
    "PlanOut",
    "PortalOut",
    "PortalRequest",
    "StripeWebhookAck",
    "SubscriptionOut",
    "UsageSummaryOut",
]
