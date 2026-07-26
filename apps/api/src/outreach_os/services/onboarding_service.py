"""Self-serve onboarding: what has this workspace actually got set up?

The checklist is derived from real state on every request rather than trusted
from a stored flag. A user who deletes their API key must see the step reopen —
a cached "done" would leave them staring at a broken product with a green tick.

`tenant.onboarding_state` is therefore only used for things that cannot be
derived, like "the user explicitly dismissed the tour".
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.domain.models.campaign import Campaign
from outreach_os.domain.models.credential import Credential
from outreach_os.domain.models.icp import Icp
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.domain.models.tenant import Tenant
from outreach_os.services.llm_credentials import PROVIDERS

# The tenant-scoped models this module counts. Spelled out rather than made
# structural: SQLAlchemy exposes `Model.tenant_id` as an InstrumentedAttribute
# at class level, which a Protocol over `Mapped[...]` does not match.
_Countable = type[Mailbox] | type[Lead] | type[Campaign] | type[Icp]


@dataclass
class OnboardingStep:
    key: str
    title: str
    description: str
    done: bool
    # False for steps the product can technically run without.
    required: bool
    # Where the web app should send the user to complete this step.
    href: str
    detail: str | None = None


@dataclass
class OnboardingStatus:
    steps: list[OnboardingStep]
    completed_at: datetime | None
    dismissed: bool

    @property
    def ready(self) -> bool:
        """Can this workspace actually generate and send an email?"""
        return all(s.done for s in self.steps if s.required)

    @property
    def next_step(self) -> OnboardingStep | None:
        return next((s for s in self.steps if s.required and not s.done), None)


async def _count(
    session: AsyncSession, model: _Countable, tenant_id: uuid.UUID
) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(model)
                .where(model.tenant_id == tenant_id)
            )
        ).scalar_one()
        or 0
    )


async def get_status(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> OnboardingStatus:
    """Derive the checklist from live workspace state."""
    tenant = await session.get(Tenant, tenant_id)

    llm_kinds = {p.credential_kind for p in PROVIDERS}
    creds = (
        (await session.execute(select(Credential).where(Credential.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    connected_llm = [c for c in creds if c.kind in llm_kinds]
    verified_llm = [c for c in connected_llm if c.last_verified_at is not None]

    n_mailboxes = await _count(session, Mailbox, tenant_id)
    n_leads = await _count(session, Lead, tenant_id)
    n_campaigns = await _count(session, Campaign, tenant_id)
    n_icps = await _count(session, Icp, tenant_id)

    steps = [
        OnboardingStep(
            key="llm_key",
            title="Connect an AI provider",
            description=(
                "Add your own API key. It is encrypted with a key unique to your "
                "workspace, and every draft is billed to your provider account."
            ),
            done=bool(connected_llm),
            required=True,
            href="/integrations",
            detail=(
                f"{len(connected_llm)} connected"
                f"{f', {len(verified_llm)} verified' if connected_llm else ''}"
                if connected_llm
                else "No provider connected yet"
            ),
        ),
        OnboardingStep(
            key="llm_verified",
            title="Verify your API key",
            description="Run a live check so you find out now, not mid-campaign.",
            done=bool(verified_llm),
            required=False,
            href="/integrations",
            detail=(
                "Key verified against the provider"
                if verified_llm
                else "Not verified yet"
            ),
        ),
        OnboardingStep(
            key="mailbox",
            title="Connect a mailbox",
            description=(
                "Outreach is sent from your own mailbox, never a shared IP, so "
                "your domain keeps its reputation."
            ),
            done=n_mailboxes > 0,
            required=True,
            href="/mailboxes",
            detail=f"{n_mailboxes} connected",
        ),
        OnboardingStep(
            key="icp",
            title="Describe your ideal customer",
            description="Tells lead discovery who to look for.",
            done=n_icps > 0,
            required=False,
            href="/icps",
            detail=f"{n_icps} defined",
        ),
        OnboardingStep(
            key="leads",
            title="Add some leads",
            description="Import a list or run a scrape against your ICP.",
            done=n_leads > 0,
            required=True,
            href="/leads",
            detail=f"{n_leads} in your workspace",
        ),
        OnboardingStep(
            key="campaign",
            title="Create a campaign",
            description=(
                "Add up to three emails you have written yourself — the agent "
                "copies your voice from them."
            ),
            done=n_campaigns > 0,
            required=True,
            href="/campaigns",
            detail=f"{n_campaigns} created",
        ),
    ]

    state = (tenant.onboarding_state or {}) if tenant else {}
    return OnboardingStatus(
        steps=steps,
        completed_at=tenant.onboarding_completed_at if tenant else None,
        dismissed=bool(state.get("dismissed")),
    )


async def mark_completed(session: AsyncSession, *, tenant_id: uuid.UUID) -> None:
    """Stamp first-completion. Idempotent, so it can be called on every check."""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is not None and tenant.onboarding_completed_at is None:
        tenant.onboarding_completed_at = datetime.now(timezone.utc)
        await session.flush()


async def set_dismissed(
    session: AsyncSession, *, tenant_id: uuid.UUID, dismissed: bool
) -> None:
    """Let a user hide the checklist without pretending the work is done."""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        return
    # Reassign rather than mutate: SQLAlchemy does not track in-place JSONB edits.
    tenant.onboarding_state = {**(tenant.onboarding_state or {}), "dismissed": dismissed}
    await session.flush()


__all__ = [
    "OnboardingStatus",
    "OnboardingStep",
    "get_status",
    "mark_completed",
    "set_dismissed",
]
