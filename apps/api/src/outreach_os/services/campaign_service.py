"""Campaign service — CRUD + step management.

Multi-tenant by construction: every read/write takes `tenant_id` and
relies on the caller (an RLS-bound session) to enforce isolation.
"""
from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from outreach_os.domain.models.campaign import Campaign
from outreach_os.domain.models.campaign_step import CampaignStep
from outreach_os.domain.schemas.phase3 import (
    CAMPAIGN_STATUSES,
    CampaignCreate,
    CampaignStepIn,
    CampaignUpdate,
)


class CampaignError(RuntimeError):
    pass


def _validate_status(status: str | None) -> None:
    if status is None:
        return
    if status not in CAMPAIGN_STATUSES:
        raise CampaignError(
            f"invalid status {status!r}; expected one of {CAMPAIGN_STATUSES}"
        )


def _validate_steps(steps: Sequence[CampaignStepIn]) -> None:
    if not steps:
        return
    seen: set[int] = set()
    for s in steps:
        if s.step_number in seen:
            raise CampaignError(f"duplicate step_number={s.step_number}")
        seen.add(s.step_number)


class CampaignService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Reads ---

    async def list_campaigns(
        self, *, tenant_id: uuid.UUID
    ) -> list[tuple[Campaign, list[CampaignStep]]]:
        result = await self.session.execute(
            select(Campaign)
            .where(Campaign.tenant_id == tenant_id)
            .options(selectinload(Campaign.steps))  # type: ignore[attr-defined]
            .order_by(Campaign.created_at.desc())
        )
        campaigns: list[Campaign] = list(result.scalars().all())
        # `selectinload` should populate steps; sort each campaign's steps.
        for c in campaigns:
            c.steps.sort(key=lambda s: s.step_number)  # type: ignore[attr-defined]
        return [(c, list(c.steps)) for c in campaigns]  # type: ignore[attr-defined]

    async def get_campaign(
        self, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> tuple[Campaign, list[CampaignStep]] | None:
        result = await self.session.execute(
            select(Campaign)
            .where(Campaign.tenant_id == tenant_id)
            .where(Campaign.id == campaign_id)
            .options(selectinload(Campaign.steps))  # type: ignore[attr-defined]
        )
        campaign = result.scalar_one_or_none()
        if campaign is None:
            return None
        campaign.steps.sort(key=lambda s: s.step_number)  # type: ignore[attr-defined]
        return campaign, list(campaign.steps)  # type: ignore[attr-defined]

    # --- Writes ---

    async def create_campaign(
        self, *, tenant_id: uuid.UUID, data: CampaignCreate
    ) -> tuple[Campaign, list[CampaignStep]]:
        _validate_steps(data.steps)
        if len(data.style_sample_emails) > 3:
            raise CampaignError("at most 3 style_sample_emails allowed")
        campaign = Campaign(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            llm_model=data.llm_model,
            style_sample_emails=list(data.style_sample_emails),
            style_notes=data.style_notes,
        )
        self.session.add(campaign)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise CampaignError(f"campaign name already exists: {data.name!r}") from exc

        steps: list[CampaignStep] = []
        for s in data.steps:
            step = CampaignStep(
                tenant_id=tenant_id,
                campaign_id=campaign.id,
                step_number=s.step_number,
                delay_days=s.delay_days,
                subject_template=s.subject_template,
                goal=s.goal,
            )
            self.session.add(step)
            steps.append(step)
        if steps:
            await self.session.flush()
        return campaign, steps

    async def update_campaign(
        self, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID, data: CampaignUpdate
    ) -> tuple[Campaign, list[CampaignStep]] | None:
        _validate_status(data.status)
        if data.style_sample_emails is not None and len(data.style_sample_emails) > 3:
            raise CampaignError("at most 3 style_sample_emails allowed")

        result = await self.session.execute(
            select(Campaign)
            .where(Campaign.tenant_id == tenant_id)
            .where(Campaign.id == campaign_id)
            .options(selectinload(Campaign.steps))  # type: ignore[attr-defined]
        )
        campaign = result.scalar_one_or_none()
        if campaign is None:
            return None

        if data.name is not None:
            campaign.name = data.name
        if data.description is not None:
            campaign.description = data.description
        if data.status is not None:
            campaign.status = data.status
        if data.style_sample_emails is not None:
            campaign.style_sample_emails = list(data.style_sample_emails)
        if data.style_notes is not None:
            campaign.style_notes = data.style_notes
        if data.llm_model is not None:
            campaign.llm_model = data.llm_model
        if data.is_active is not None:
            campaign.is_active = data.is_active

        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise CampaignError(f"campaign name already exists: {data.name!r}") from exc
        campaign.steps.sort(key=lambda s: s.step_number)  # type: ignore[attr-defined]
        return campaign, list(campaign.steps)  # type: ignore[attr-defined]

    async def replace_steps(
        self,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        steps: list[CampaignStepIn],
    ) -> list[CampaignStep] | None:
        """Atomically replace the campaign's steps. Returns None if the
        campaign doesn't exist for this tenant."""
        result = await self.session.execute(
            select(Campaign)
            .where(Campaign.tenant_id == tenant_id)
            .where(Campaign.id == campaign_id)
        )
        campaign = result.scalar_one_or_none()
        if campaign is None:
            return None

        # Wipe existing steps. FKs from draft.step_id use ON DELETE CASCADE,
        # so any draft referencing these steps will be removed too.
        await self.session.execute(
            delete(CampaignStep)
            .where(CampaignStep.tenant_id == tenant_id)
            .where(CampaignStep.campaign_id == campaign_id)
        )
        await self.session.flush()

        new_steps: list[CampaignStep] = []
        for s in steps:
            step = CampaignStep(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                step_number=s.step_number,
                delay_days=s.delay_days,
                subject_template=s.subject_template,
                goal=s.goal,
            )
            self.session.add(step)
            new_steps.append(step)
        if new_steps:
            await self.session.flush()
        return new_steps

    async def delete_campaign(
        self, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> bool:
        result = await self.session.execute(
            delete(Campaign)
            .where(Campaign.tenant_id == tenant_id)
            .where(Campaign.id == campaign_id)
        )
        return (result.rowcount or 0) > 0
