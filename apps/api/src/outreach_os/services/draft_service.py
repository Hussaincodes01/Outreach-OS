"""Draft service — generates, fetches, and approves email drafts.

The heavy lifting happens in `services.agent.run_agent` (the LangGraph
pipeline). This service:

1. Persists an `AgentRun` row (status=running) before invoking the agent,
   then updates it (status=completed/failed) afterwards with trace + token
   counts.
2. Saves the generated body to S3 with `build_draft_key(...)`. We also
   keep a `body_preview` inline (first 280 chars) so the UI can render
   the draft without an S3 round-trip.
3. Ensures the unique (campaign_id, lead_id, step_id) constraint is
   respected: re-running for the same triple with `force_regenerate=True`
   deletes the old draft and re-creates it.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.config import get_settings
from outreach_os.core.llm import LLMClient
from outreach_os.core.s3 import (
    S3Error,
    build_draft_key,
    download_text,
    ensure_bucket,
    presign_get,
    upload_text,
)
from outreach_os.domain.models.agent_run import AgentRun
from outreach_os.domain.models.campaign_step import CampaignStep
from outreach_os.domain.models.draft import Draft
from outreach_os.domain.schemas.phase3 import DRAFT_STATUSES, DraftOut
from outreach_os.services.agent import (
    AgentInputError,
    run_agent,
)
from outreach_os.services.llm_credentials import MissingLLMCredentialsError

log = logging.getLogger(__name__)


class DraftError(RuntimeError):
    pass


@dataclass
class DraftGenerationResult:
    draft_id: uuid.UUID
    agent_run_id: uuid.UUID
    status: str
    subject: str | None
    body_preview: str | None
    model_used: str | None
    error: str | None


def _body_preview(body: str, *, limit: int = 280) -> str:
    s = (body or "").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def draft_row_to_out(d: Draft) -> DraftOut:
    return DraftOut(
        id=d.id,
        created_at=d.created_at,
        updated_at=d.updated_at,
        tenant_id=d.tenant_id,
        campaign_id=d.campaign_id,
        lead_id=d.lead_id,
        step_id=d.step_id,
        status=d.status,
        subject=d.subject,
        body_preview=d.body_preview,
        s3_key=d.s3_key,
        model_used=d.model_used,
        error=d.error,
        body=None,
        download_url=None,
    )


class DraftService:
    def __init__(self, session: AsyncSession, *, llm: LLMClient | None = None) -> None:
        self.session = session
        # None in production: the agent resolves a client from the tenant's own
        # key (BYOK). Tests inject a deterministic fake here.
        self.llm = llm
        self.settings = get_settings()

    # --- Reads ---

    async def list_drafts(
        self,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DraftOut], int]:
        from sqlalchemy import func

        if status is not None and status not in DRAFT_STATUSES:
            raise DraftError(
                f"invalid status {status!r}; expected one of {DRAFT_STATUSES}"
            )

        base = select(Draft).where(Draft.tenant_id == tenant_id)
        count_q = select(func.count(Draft.id)).where(Draft.tenant_id == tenant_id)
        if campaign_id is not None:
            base = base.where(Draft.campaign_id == campaign_id)
            count_q = count_q.where(Draft.campaign_id == campaign_id)
        if status is not None:
            base = base.where(Draft.status == status)
            count_q = count_q.where(Draft.status == status)

        total = int((await self.session.execute(count_q)).scalar_one() or 0)
        result = await self.session.execute(
            base.order_by(Draft.created_at.desc()).limit(limit).offset(offset)
        )
        drafts = list(result.scalars().all())
        return [draft_row_to_out(d) for d in drafts], total

    async def get_draft(
        self,
        *,
        tenant_id: uuid.UUID,
        draft_id: uuid.UUID,
        include_body: bool = False,
    ) -> DraftOut | None:
        result = await self.session.execute(
            select(Draft)
            .where(Draft.tenant_id == tenant_id)
            .where(Draft.id == draft_id)
        )
        d = result.scalar_one_or_none()
        if d is None:
            return None
        out = draft_row_to_out(d)
        if include_body and d.s3_key:
            bucket = self.settings.s3_drafts_bucket
            try:
                out.body = download_text(bucket, d.s3_key)
                out.download_url = presign_get(bucket, d.s3_key)
            except S3Error as exc:
                log.warning("failed to fetch draft body: %s", exc)
                out.body = None
                out.download_url = None
        return out

    # --- Writes ---

    async def update_draft(
        self,
        *,
        tenant_id: uuid.UUID,
        draft_id: uuid.UUID,
        new_status: str | None = None,
        new_subject: str | None = None,
        new_body_preview: str | None = None,
    ) -> DraftOut | None:
        if new_status is not None and new_status not in DRAFT_STATUSES:
            raise DraftError(
                f"invalid status {new_status!r}; expected one of {DRAFT_STATUSES}"
            )
        result = await self.session.execute(
            select(Draft)
            .where(Draft.tenant_id == tenant_id)
            .where(Draft.id == draft_id)
        )
        d = result.scalar_one_or_none()
        if d is None:
            return None
        if new_status is not None:
            d.status = new_status
        if new_subject is not None:
            d.subject = new_subject
        if new_body_preview is not None:
            d.body_preview = new_body_preview
        await self.session.flush()
        return draft_row_to_out(d)

    # --- Generation ---

    async def generate_draft(
        self,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        lead_id: uuid.UUID,
        step_id: uuid.UUID,
        force_regenerate: bool = False,
    ) -> DraftGenerationResult:
        """Run the agent pipeline synchronously. The caller (API or Celery
        task) decides whether to await this inline or dispatch it."""
        # Validate step belongs to campaign (RLS will already scope this).
        step_result = await self.session.execute(
            select(CampaignStep)
            .where(CampaignStep.tenant_id == tenant_id)
            .where(CampaignStep.id == step_id)
            .where(CampaignStep.campaign_id == campaign_id)
        )
        step = step_result.scalar_one_or_none()
        if step is None:
            raise DraftError("step does not belong to this campaign")

        # If a draft already exists for (campaign, lead, step), either
        # delete it (force) or refuse (idempotent).
        existing_q = (
            select(Draft)
            .where(Draft.tenant_id == tenant_id)
            .where(Draft.campaign_id == campaign_id)
            .where(Draft.lead_id == lead_id)
            .where(Draft.step_id == step_id)
        )
        existing = (await self.session.execute(existing_q)).scalar_one_or_none()
        if existing is not None:
            if not force_regenerate:
                return DraftGenerationResult(
                    draft_id=existing.id,
                    agent_run_id=uuid.uuid4(),
                    status=existing.status,
                    subject=existing.subject,
                    body_preview=existing.body_preview,
                    model_used=existing.model_used,
                    error=existing.error,
                )
            await self.session.execute(
                delete(Draft)
                .where(Draft.tenant_id == tenant_id)
                .where(Draft.id == existing.id)
            )
            await self.session.flush()

        # Pre-create the draft in 'pending' state so the unique index holds.
        draft = Draft(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            step_id=step_id,
            status="pending",
        )
        self.session.add(draft)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise DraftError(f"draft conflict: {exc}") from exc

        # Pre-create the AgentRun in 'running' state.
        run = AgentRun(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            draft_id=draft.id,
            status="running",
            started_at=__import__("datetime").datetime.utcnow(),
        )
        self.session.add(run)
        await self.session.flush()

        # Run the agent. Any failure here is captured into the AgentRun
        # and the Draft (status=failed) — we never raise out of this method.
        try:
            result = await run_agent(
                session=self.session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                lead_id=lead_id,
                step_id=step_id,
                llm=self.llm,
            )
        except AgentInputError as exc:
            run.status = "failed"
            run.error = str(exc)[:500]
            run.completed_at = __import__("datetime").datetime.utcnow()
            draft.status = "failed"
            draft.error = str(exc)[:500]
            await self.session.flush()
            return DraftGenerationResult(
                draft_id=draft.id,
                agent_run_id=run.id,
                status="failed",
                subject=None,
                body_preview=None,
                model_used=None,
                error=run.error,
            )
        except MissingLLMCredentialsError as exc:
            # Expected setup state, not a crash: the tenant hasn't connected a
            # key yet. Surface the actionable message on the draft row and keep
            # it out of the error logs.
            log.info("draft skipped, no LLM key for tenant %s", tenant_id)
            run.status = "failed"
            run.error = str(exc)[:500]
            run.completed_at = __import__("datetime").datetime.utcnow()
            draft.status = "failed"
            draft.error = str(exc)[:500]
            await self.session.flush()
            return DraftGenerationResult(
                draft_id=draft.id,
                agent_run_id=run.id,
                status="failed",
                subject=None,
                body_preview=None,
                model_used=None,
                error=run.error,
            )
        except Exception as exc:
            log.exception("agent run failed")
            run.status = "failed"
            run.error = str(exc)[:500]
            run.completed_at = __import__("datetime").datetime.utcnow()
            draft.status = "failed"
            draft.error = str(exc)[:500]
            await self.session.flush()
            return DraftGenerationResult(
                draft_id=draft.id,
                agent_run_id=run.id,
                status="failed",
                subject=None,
                body_preview=None,
                model_used=None,
                error=run.error,
            )

        # Persist the body to S3. S3 failure is non-fatal — we still keep
        # the inline preview so the user can read the draft.
        bucket = self.settings.s3_drafts_bucket
        s3_key: str | None = None
        try:
            ensure_bucket(bucket)
            s3_key = build_draft_key(
                str(tenant_id), str(draft.id), step_number=step.step_number
            )
            upload_text(bucket, s3_key, result.body)
        except S3Error as exc:
            log.warning("S3 upload failed for draft %s: %s", draft.id, exc)
            s3_key = None

        # Update the draft + agent_run rows.
        draft.status = "ready"
        draft.subject = result.subject
        draft.body_preview = _body_preview(result.body)
        draft.s3_key = s3_key
        draft.model_used = result.model
        draft.error = None

        run.status = "completed"
        run.completed_at = result.completed_at
        run.input_tokens = result.input_tokens
        run.output_tokens = result.output_tokens
        run.trace = result.trace

        await self.session.flush()
        return DraftGenerationResult(
            draft_id=draft.id,
            agent_run_id=run.id,
            status=draft.status,
            subject=draft.subject,
            body_preview=draft.body_preview,
            model_used=draft.model_used,
            error=None,
        )

    # --- Agent runs (read-only for now) ---

    async def list_agent_runs(
        self,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        q = (
            select(AgentRun)
            .where(AgentRun.tenant_id == tenant_id)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
        if campaign_id is not None:
            q = q.where(AgentRun.campaign_id == campaign_id)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    # --- Dispatch (eager-mode-aware) ---

    async def dispatch_generate_draft(
        self,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        lead_id: uuid.UUID,
        step_id: uuid.UUID,
        force_regenerate: bool = False,
    ) -> DraftGenerationResult:
        """Run the agent pipeline, in-process in tests, queued to Celery in prod.

        In production we return a placeholder `DraftGenerationResult` (status=pending)
        after a Celery worker picks up the task from the broker. In tests
        (eager mode) we `await` the async core directly so the same event
        loop drives both the HTTP request and the worker logic.
        """
        from outreach_os.core.config import get_settings

        settings = get_settings()
        if settings.celery_task_always_eager:
            from outreach_os.workers.tasks.draft import generate_draft_async

            return await generate_draft_async(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                lead_id=lead_id,
                step_id=step_id,
                force_regenerate=force_regenerate,
            )
        from outreach_os.workers.tasks.draft import generate_draft

        generate_draft.delay(
            str(tenant_id), str(campaign_id), str(lead_id), str(step_id), force_regenerate
        )
        # Return a placeholder — the worker will populate the draft row
        # in the background. Callers should poll GET /v1/drafts/{id} or
        # watch the campaign's draft list.
        return DraftGenerationResult(
            draft_id=uuid.uuid4(),
            agent_run_id=uuid.uuid4(),
            status="pending",
            subject=None,
            body_preview=None,
            model_used=None,
            error=None,
        )


# --- Helper for typed output rows ------------------------------------------


def agent_run_to_dict(r: AgentRun) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "tenant_id": str(r.tenant_id),
        "campaign_id": str(r.campaign_id),
        "draft_id": str(r.draft_id) if r.draft_id else None,
        "status": r.status,
        "trace": r.trace,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "embeddings_tokens": r.embeddings_tokens,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "error": r.error,
        "created_at": r.created_at.isoformat(),
    }
