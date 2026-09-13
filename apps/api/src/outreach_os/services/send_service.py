"""SendService — turn a SequenceStep into a delivered email.

Responsibilities:
- Resolve a Draft (regenerate if missing) for the (lead, step) pair.
- Inject tracking pixel + unsubscribe footer (with disclosure line).
- Honour per-mailbox daily send caps.
- Jitter scheduled time so we don't burst.
- Hand off to MailerClient and persist Send status.
- Promote / fail the parent SequenceStep.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from email.utils import make_msgid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.config import get_settings
from outreach_os.core.errors import MailError
from outreach_os.core.llm import LLMClient
from outreach_os.core.mailer import (
    MailerClient,
    MailerError,
    OutgoingMessage,
    get_mailer_override,
)
from outreach_os.domain.models.campaign_step import CampaignStep
from outreach_os.domain.models.draft import Draft
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.domain.models.send import Send
from outreach_os.domain.models.sequence_step import SequenceStep
from outreach_os.domain.models.suppression import Suppression
from outreach_os.services.draft_service import DraftGenerationResult, DraftService
from outreach_os.services.mailbox.transport import mailer_for_mailbox

log = logging.getLogger(__name__)


class SendError(RuntimeError):
    pass


class SendService:
    def __init__(self, session: AsyncSession, *, llm: LLMClient | None = None, mailer: MailerClient | None = None) -> None:
        self.session = session
        self.llm = llm
        # Precedence: constructor-injected mailer > process override installed
        # via `set_mailer_client` (the test hook) > the sending mailbox's own
        # SMTP (resolved per-step in `execute_step`). Deliberately no fallback
        # to the platform `get_mailer_client()` here — a shared SmtpMailer/
        # StubMailer must never carry campaign sends.
        self._mailer = mailer or get_mailer_override()
        self.settings = get_settings()

    # --- Query helpers ---

    async def is_suppressed(self, *, tenant_id: uuid.UUID, email: str) -> bool:
        row = (
            await self.session.execute(
                select(Suppression.id).where(
                    Suppression.tenant_id == tenant_id,
                    Suppression.email == email,
                )
            )
        ).scalar_one_or_none()
        return row is not None

    async def sent_count_today(
        self, *, tenant_id: uuid.UUID, mailbox_id: uuid.UUID
    ) -> int:
        from datetime import datetime as _dt
        start_of_day = _dt.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.session.execute(
            select(func.count(Send.id)).where(
                Send.tenant_id == tenant_id,
                Send.mailbox_id == mailbox_id,
                Send.sent_at >= start_of_day,
            )
        )
        return int(result.scalar_one() or 0)

    # --- Core ---

    async def execute_due(
        self, *, tenant_id: uuid.UUID, limit: int | None = None
    ) -> list[Send]:
        """Run a pass: find queued-but-due steps, build sends, fire them.

        Returns the list of Send rows that were attempted (any status).
        """
        limit = limit or self.settings.send_batch_size
        now = datetime.utcnow()
        # Pick the first `limit` pending/queued steps that are due.
        result = await self.session.execute(
            select(SequenceStep)
            .where(
                SequenceStep.tenant_id == tenant_id,
                SequenceStep.status.in_(("pending", "queued")),
                SequenceStep.scheduled_at <= now,
            )
            .order_by(SequenceStep.scheduled_at)
            .limit(limit)
        )
        steps = list(result.scalars().all())
        sent: list[Send] = []
        for step in steps:
            try:
                send = await self.execute_step(tenant_id=tenant_id, step=step)
                if send is not None:
                    sent.append(send)
            except Exception as exc:
                log.exception("execute_step failed: %s", exc)
                step.status = "failed"
                step.stop_reason = str(exc)[:200]
            # Flush after every step so the daily-cap SELECT for the next
            # step sees the freshly-inserted Send row.
            await self.session.flush()
        return sent

    async def execute_step(
        self, *, tenant_id: uuid.UUID, step: SequenceStep
    ) -> Send | None:
        # 1. Suppression check.
        lead = (
            await self.session.execute(
                select(Lead).where(Lead.tenant_id == tenant_id, Lead.id == step.lead_id)
            )
        ).scalar_one_or_none()
        if lead is None or not lead.email:
            step.status = "skipped"
            step.stop_reason = "lead missing or no email"
            return None
        if await self.is_suppressed(tenant_id=tenant_id, email=lead.email):
            step.status = "skipped"
            step.stop_reason = "suppressed"
            return None

        # 2. Pick a mailbox (first active one for the tenant).
        mailbox = (
            await self.session.execute(
                select(Mailbox)
                .where(Mailbox.tenant_id == tenant_id, Mailbox.is_active.is_(True))
                .order_by(Mailbox.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if mailbox is None:
            step.status = "failed"
            step.stop_reason = "no active mailbox"
            return None

        # 3. Daily cap.
        cap = mailbox.daily_send_cap or self.settings.default_daily_send_cap
        if await self.sent_count_today(
            tenant_id=tenant_id, mailbox_id=mailbox.id
        ) >= cap:
            step.status = "queued"  # Will retry next pass.
            return None

        # 4. Ensure a Draft exists (regenerate if missing).
        draft = await self._ensure_draft(
            tenant_id=tenant_id, step=step, lead=lead
        )
        if draft is None or not draft.body_preview:
            step.status = "failed"
            step.stop_reason = "draft generation failed"
            return None

        # 5. Build the body (preview only — production fetches full body from S3).
        body_text = draft.body_preview or ""
        body_text = self._inject_footer(body=body_text, lead=lead, send_id=uuid.uuid4())

        # 6. Compose Message-ID and headers.
        send_id = uuid.uuid4()
        message_id = make_msgid(domain="outreach-os.local")
        subject = draft.subject or "Quick question"

        # 7. Persist the Send row (queued) before we hand off to the mailer.
        send = Send(
            id=send_id,
            tenant_id=tenant_id,
            step_id=step.id,
            mailbox_id=mailbox.id,
            draft_id=draft.id,
            to_email=lead.email,
            from_email=mailbox.email_address,
            subject=subject,
            body_text=body_text,
            message_id_header=message_id,
            status="queued",
        )
        self.session.add(send)
        await self.session.flush()

        # 8. Hand off to the mailer. Resolve it here (not in __init__) so a
        # decrypt/config failure on THIS mailbox marks only this send failed,
        # rather than raising before the batch even starts.
        try:
            mailer = self._mailer or mailer_for_mailbox(mailbox)
            receipt = mailer.send(
                OutgoingMessage(
                    to_email=lead.email,
                    from_email=mailbox.email_address,
                    subject=subject,
                    body_text=body_text,
                    message_id_header=message_id,
                    in_reply_to=None,
                    references=None,
                )
            )
        except (MailerError, MailError) as exc:
            send.status = "failed"
            send.error = str(exc)[:500]
            step.attempts += 1
            step.status = "failed"
            step.stop_reason = f"mailer error: {str(exc)[:120]}"
            # Phase 6: surface the failure.
            try:
                from outreach_os.services.notification_service import publish

                await publish(
                    self.session,
                    tenant_id=tenant_id,
                    event_key="send.failed",
                    severity="error",
                    title=f"Send failed: {lead.email or 'lead'}",
                    body=(send.error or "")[:280],
                    target_type="send",
                    target_id=send.id,
                    payload={
                        "step_id": str(step.id),
                        "lead_id": str(lead.id),
                    },
                )
            except Exception:
                log.warning("notification dispatch failed for send.failed", exc_info=True)
            return send

        send.provider_message_id = receipt.provider_message_id
        send.status = "sent"
        send.sent_at = datetime.utcnow()
        step.status = "sent"
        step.sent_at = send.sent_at
        step.attempts += 1
        return send

    # --- Helpers ---

    async def _ensure_draft(
        self,
        *,
        tenant_id: uuid.UUID,
        step: SequenceStep,
        lead: Lead,
    ) -> Draft | None:
        if step.draft_id:
            existing = (
                await self.session.execute(
                    select(Draft).where(
                        Draft.tenant_id == tenant_id, Draft.id == step.draft_id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
        # Need to generate. Resolve the campaign_step for context.
        cs = (
            await self.session.execute(
                select(CampaignStep).where(
                    CampaignStep.tenant_id == tenant_id,
                    CampaignStep.id == step.campaign_step_id,
                )
            )
        ).scalar_one_or_none()
        if cs is None:
            return None
        svc = DraftService(self.session, llm=self.llm)
        try:
            result: DraftGenerationResult = await svc.generate_draft(
                tenant_id=tenant_id,
                campaign_id=cs.campaign_id,
                lead_id=lead.id,
                step_id=cs.id,
            )
        except Exception as exc:
            log.exception("draft generation failed: %s", exc)
            return None
        if result.status != "ready":
            return None
        step.draft_id = result.draft_id
        return (
            await self.session.execute(
                select(Draft).where(
                    Draft.tenant_id == tenant_id, Draft.id == result.draft_id
                )
            )
        ).scalar_one_or_none()

    def _inject_footer(self, *, body: str, lead: Lead, send_id: uuid.UUID) -> str:
        base = self.settings.public_base_url.rstrip("/")
        unsub_url = f"{base}/t/unsubscribe?email={lead.email}&tenant={lead.tenant_id}"
        pixel_url = f"{base}/t/open/{send_id}.png"
        disclosure = self.settings.email_disclosure
        footer = (
            f"\n\n--\n{disclosure}\n"
            f"Unsubscribe: {unsub_url}\n"
            f"<img src=\"{pixel_url}\" width=\"1\" height=\"1\" alt=\"\" />"
        )
        return body + footer

    # --- Read paths used by the API ---

    async def list_sends(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID | None = None,
        step_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Send], int]:
        conds = [Send.tenant_id == tenant_id]
        if run_id is not None:
            conds.append(SequenceStep.run_id == run_id)
            stmt = (
                select(Send)
                .join(SequenceStep, SequenceStep.id == Send.step_id)
                .where(*conds)
            )
        else:
            stmt = select(Send).where(*conds)
        if step_id is not None:
            conds.append(Send.step_id == step_id)
        if status is not None:
            conds.append(Send.status == status)
        if run_id is not None:
            stmt = (
                select(Send)
                .join(SequenceStep, SequenceStep.id == Send.step_id)
                .where(*conds)
            )
        else:
            stmt = select(Send).where(*conds)
        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar_one()
        result = await self.session.execute(
            stmt.order_by(Send.queued_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def get_send(
        self, *, tenant_id: uuid.UUID, send_id: uuid.UUID
    ) -> Send | None:
        return (
            await self.session.execute(
                select(Send).where(
                    Send.tenant_id == tenant_id, Send.id == send_id
                )
            )
        ).scalar_one_or_none()
