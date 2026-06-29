"""SequenceService — manage a SequenceRun's lifecycle.

`start_run` materializes the (lead, campaign_step) tuples into
`sequence_step` rows with computed scheduled_at. `advance_due_steps`
enqueues any steps whose scheduled_at has passed and re-evaluates
follow-ups after a reply. `stop_run` halts the run with a reason.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.config import get_settings
from outreach_os.domain.models.campaign import Campaign
from outreach_os.domain.models.campaign_step import CampaignStep
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.sequence_run import SequenceRun
from outreach_os.domain.models.sequence_step import SequenceStep
from outreach_os.domain.models.suppression import Suppression


class SequenceError(RuntimeError):
    pass


class SequenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    async def start_run(
        self,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        name: str,
        lead_ids: Sequence[uuid.UUID],
        start_at: datetime | None = None,
        ignore_caps: bool = False,
    ) -> SequenceRun:
        # Validate campaign. Eager-load the steps relationship so we can
        # sort it after the query returns (avoid lazy-load greenlet error).
        from sqlalchemy.orm import selectinload
        camp = (
            await self.session.execute(
                select(Campaign)
                .where(
                    Campaign.tenant_id == tenant_id, Campaign.id == campaign_id
                )
                .options(selectinload(Campaign.steps))
            )
        ).scalar_one_or_none()
        if camp is None:
            raise SequenceError(f"campaign {campaign_id} not found")
        steps: list[CampaignStep] = sorted(camp.steps, key=lambda s: s.step_number)
        if not steps:
            raise SequenceError("campaign has no steps to run")
        # Validate leads exist + aren't suppressed.
        leads = (
            await self.session.execute(
                select(Lead).where(
                    Lead.tenant_id == tenant_id, Lead.id.in_(list(lead_ids))
                )
            )
        ).scalars().all()
        if len(leads) != len(set(lead_ids)):
            raise SequenceError("one or more lead_ids not found for this tenant")
        suppressions = (
            await self.session.execute(
                select(Suppression.email).where(
                    Suppression.tenant_id == tenant_id,
                    Suppression.email.in_([l.email for l in leads if l.email]),
                )
            )
        ).scalars().all()
        suppressed = {e.lower() for e in suppressions if e}
        if suppressed:
            # Skip suppressed leads silently.
            leads = [l for l in leads if (l.email or "").lower() not in suppressed]

        # Create the run.
        run = SequenceRun(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            name=name,
            status="running",
        )
        self.session.add(run)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise SequenceError(f"sequence run name already exists: {name!r}") from exc

        # Materialize (lead, step) tuples with scheduled_at.
        start = start_at or datetime.utcnow()
        for lead in leads:
            for idx, cs in enumerate(steps):
                scheduled = start + timedelta(days=sum(
                    steps[j].delay_days for j in range(idx + 1)
                ))
                step = SequenceStep(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    lead_id=lead.id,
                    campaign_step_id=cs.id,
                    status="pending",
                    scheduled_at=scheduled,
                )
                self.session.add(step)
        await self.session.flush()
        return run

    async def stop_run(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        reason: str = "manual",
    ) -> SequenceRun | None:
        run = (
            await self.session.execute(
                select(SequenceRun).where(
                    SequenceRun.tenant_id == tenant_id, SequenceRun.id == run_id
                )
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        run.status = "stopped"
        run.stopped_reason = reason
        run.stopped_at = datetime.utcnow()
        # Stop any unsent steps too.
        pending = (
            await self.session.execute(
                select(SequenceStep).where(
                    SequenceStep.tenant_id == tenant_id,
                    SequenceStep.run_id == run_id,
                    SequenceStep.status.in_(("pending", "queued")),
                )
            )
        ).scalars().all()
        for s in pending:
            s.status = "stopped"
            s.stop_reason = reason
        await self.session.flush()
        return run

    async def get_run(
        self, *, tenant_id: uuid.UUID, run_id: uuid.UUID
    ) -> tuple[SequenceRun, list[SequenceStep]] | None:
        from sqlalchemy.orm import selectinload
        run = (
            await self.session.execute(
                select(SequenceRun)
                .where(
                    SequenceRun.tenant_id == tenant_id, SequenceRun.id == run_id
                )
                .options(selectinload(SequenceRun.steps))
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        steps = (
            await self.session.execute(
                select(SequenceStep)
                .where(
                    SequenceStep.tenant_id == tenant_id,
                    SequenceStep.run_id == run_id,
                )
                .order_by(SequenceStep.scheduled_at)
            )
        ).scalars().all()
        return run, list(steps)

    async def list_runs(
        self, *, tenant_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[SequenceRun]:
        result = await self.session.execute(
            select(SequenceRun)
            .where(SequenceRun.tenant_id == tenant_id)
            .order_by(SequenceRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def run_stats(
        self, *, tenant_id: uuid.UUID, run_id: uuid.UUID
    ) -> dict[str, int]:
        result = await self.session.execute(
            select(SequenceStep.status, func.count(SequenceStep.id))
            .where(
                SequenceStep.tenant_id == tenant_id,
                SequenceStep.run_id == run_id,
            )
            .group_by(SequenceStep.status)
        )
        out = {"step_count": 0, "pending": 0, "sent": 0, "replied": 0, "stopped": 0}
        for status, count in result.all():
            out["step_count"] += count
            if status == "pending":
                out["pending"] = count
            elif status == "sent":
                out["sent"] = count
            elif status == "replied":
                out["replied"] = count
            elif status == "stopped":
                out["stopped"] = count
        return out
