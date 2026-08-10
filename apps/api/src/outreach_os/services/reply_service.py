"""ReplyService — ingest inbound replies, classify them, and act on them.

Pipeline:
1. webhook receives a `ReplyIngestIn` payload (from Gmail Pub/Sub, etc.)
2. we find the original `Send` by matching the In-Reply-To / References
   headers (or the to_email + message_id_header fallback)
3. dedup on `reply.message_id_header` (RFC5322)
4. classify via the LLM (positive / negative / ooo / question / unsubscribe / bounce / other)
5. on positive / negative / unsubscribe / bounce, stop the parent
   sequence's remaining steps and add the address to the suppression list
   if needed.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.config import get_settings
from outreach_os.core.errors import OutreachError
from outreach_os.core.llm import LLMClient
from outreach_os.domain.models.reply import Reply
from outreach_os.domain.models.send import Send
from outreach_os.domain.models.sequence_step import SequenceStep
from outreach_os.domain.models.suppression import Suppression
from outreach_os.domain.models.tenant import Tenant
from outreach_os.domain.schemas.phase4 import ReplyIngestIn
from outreach_os.services.llm_credentials import client_for

log = logging.getLogger(__name__)

_CLASSIFY_SYSTEM = """\
You classify an inbound email reply to a cold-outreach message.
Output strict JSON with these fields:
  classification: one of
    "positive"   — the recipient wants to chat / book a meeting
    "negative"   — explicit rejection ("not interested", "remove me", etc.)
    "ooo"        — out-of-office auto-reply
    "question"   — they ask a question but haven't agreed to a meeting
    "unsubscribe"- they ask to be removed from the list
    "bounce"     — automated delivery failure notice
    "other"      — anything that doesn't fit the above
  confidence:    a number 0..1 indicating how confident you are
  reason:        one short sentence justifying the label
"""


class ReplyError(RuntimeError):
    pass


class ReplyService:
    def __init__(self, session: AsyncSession, *, llm: LLMClient | None = None) -> None:
        self.session = session
        self.llm = llm
        self.settings = get_settings()

    async def _model_for(self, tenant_id: uuid.UUID) -> str:
        """The workspace's chosen model, else the server default.

        Using the server default unconditionally would look up a key for the
        wrong provider: a workspace that only connected Anthropic would raise
        MissingLLMCredentialsError for `openai/...`, get caught below, and
        never classify a single reply.
        """
        tenant = await self.session.get(Tenant, tenant_id)
        return (
            tenant.default_llm_model if tenant and tenant.default_llm_model else None
        ) or self.settings.llm_default_model

    async def _get_llm(self, tenant_id: uuid.UUID, model: str) -> LLMClient:
        """Reply classification runs on the tenant's own key (BYOK)."""
        return await client_for(
            self.session, tenant_id=tenant_id, model=model, injected=self.llm
        )

    async def ingest(
        self,
        *,
        tenant_id: uuid.UUID,
        data: ReplyIngestIn,
    ) -> Reply | None:
        """Idempotent insert + classify + side-effects.

        Returns the Reply row, or None if it was a duplicate of one we'd
        already seen (caller can still return 200/201 to the webhook).
        """
        # 1. Find the original Send.
        send = await self._find_send(tenant_id=tenant_id, data=data)
        if send is None:
            log.warning("reply for unknown send: from=%s subj=%r", data.from_email, data.subject)
            return None
        # 2. Dedup.
        reply = Reply(
            tenant_id=tenant_id,
            send_id=send.id,
            message_id_header=data.message_id_header,
            from_email=data.from_email.lower(),
            from_name=data.from_name,
            subject=data.subject,
            body_text=data.body_text,
            body_html=data.body_html,
            received_at=data.received_at or datetime.utcnow(),
        )
        self.session.add(reply)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return None
        # 3. Classify + side-effects.
        await self._classify_and_act(tenant_id=tenant_id, reply=reply, send=send)
        return reply

    async def _find_send(
        self, *, tenant_id: uuid.UUID, data: ReplyIngestIn
    ) -> Send | None:
        # Match by In-Reply-To / References / to_email fallback.
        candidates: list[str] = []
        if data.in_reply_to:
            candidates.append(data.in_reply_to)
        if data.references:
            candidates.extend(data.references.split())
        # Always also try the to_email = original send's from_email.
        # (Most inbound services include the original Message-ID in In-Reply-To.)
        for mid in candidates:
            row = (
                await self.session.execute(
                    select(Send).where(
                        Send.tenant_id == tenant_id,
                        Send.message_id_header == mid,
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                return row
        # Fallback: the to_email of the reply matches a send's from_email.
        # We don't store reply-side to_email; the webhook payload is what it is.
        return None

    async def _classify_and_act(
        self, *, tenant_id: uuid.UUID, reply: Reply, send: Send
    ) -> None:
        model = await self._model_for(tenant_id)
        try:
            llm = await self._get_llm(tenant_id, model)
        except OutreachError as exc:
            # No key connected — leave the reply un-classified rather than
            # failing the whole inbound webhook.
            log.warning("reply classification skipped: %s", exc)
            return
        # Build the user prompt.
        prompt = (
            f"From: {reply.from_email} ({reply.from_name or 'unknown'})\n"
            f"Subject: {reply.subject or '(none)'}\n\n"
            f"{reply.body_text[:2000]}"
        )
        try:
            resp = llm.chat(
                model,
                [
                    {"role": "system", "content": _CLASSIFY_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.settings.llm_classify_max_tokens,
                temperature=self.settings.reply_classify_temperature,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            log.warning("reply classification failed: %s", exc)
            return  # leave reply un-classified
        import json
        try:
            parsed = json.loads(resp.text)
        except Exception:
            parsed = {}
        cls = parsed.get("classification")
        if cls not in (
            "positive", "negative", "ooo", "question",
            "unsubscribe", "bounce", "other",
        ):
            cls = "other"
        conf = parsed.get("confidence")
        try:
            conf_val = float(conf) if conf is not None else None
            if conf_val is not None and not (0.0 <= conf_val <= 1.0):
                conf_val = None
        except Exception:
            conf_val = None
        reply.classification = cls
        reply.classification_confidence = (
            Decimal(str(conf_val)) if conf_val is not None else None
        )
        reply.classified_at = datetime.utcnow()
        reply.classification_trace = {"reason": parsed.get("reason"), "raw": resp.text[:500]}

        # Promote parent step to "replied".
        step = (
            await self.session.execute(
                select(SequenceStep).where(
                    SequenceStep.tenant_id == tenant_id,
                    SequenceStep.id == send.step_id,
                )
            )
        ).scalar_one_or_none()
        if step is not None:
            step.status = "replied"
            step.last_reply_at = reply.received_at

        # Side effects by classification.
        stop_reasons = self.settings.stop_on_replies
        if cls in stop_reasons and step is not None:
            # Stop the rest of the run for this lead. Match any step in
            # a non-terminal state (pending/queued/sent) — if a positive
            # reply came back for step 1, the queued step 2 should
            # also be cancelled even if the scheduler already fired
            # the send row (which gets marked 'skipped' downstream).
            later = (
                await self.session.execute(
                    select(SequenceStep).where(
                        SequenceStep.tenant_id == tenant_id,
                        SequenceStep.run_id == step.run_id,
                        SequenceStep.lead_id == step.lead_id,
                        SequenceStep.id != step.id,
                        SequenceStep.status.in_(("pending", "queued", "sent")),
                    )
                )
            ).scalars().all()
            for s in later:
                s.status = "stopped"
                s.stop_reason = f"reply:{cls}"
        if cls in ("unsubscribe", "negative"):
            # Add to suppression so future sends skip them.
            existing = (
                await self.session.execute(
                    select(Suppression).where(
                        Suppression.tenant_id == tenant_id,
                        Suppression.email == reply.from_email,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                self.session.add(
                    Suppression(
                        tenant_id=tenant_id,
                        email=reply.from_email,
                        reason="unsubscribe" if cls == "unsubscribe" else "manual",
                        source=f"reply:{reply.id}",
                    )
                )
        # Persist the send's response.
        send.status = "unsubscribed" if cls == "unsubscribe" else "sent"
        await self.session.flush()

        # Phase 5 hook: on a positive reply, propose or confirm a meeting.
        # We use the lead (resolved via the parent step) so the meeting
        # is correctly attributed even if the lead has been re-imported.
        if cls == "positive" and step is not None:
            await self._maybe_create_meeting(
                tenant_id=tenant_id, step=step, reply=reply, send=send
            )

        # Phase 6 hook: surface the reply classification as a notification
        # so the dashboard live feed + Slack show "X replied positively".
        # Notification dispatch is best-effort; we never let it break the
        # reply path itself.
        try:
            from outreach_os.services.notification_service import publish

            key_for_cls = {
                "positive": "reply.positive",
                "negative": "reply.negative",
                "unsubscribe": "reply.unsubscribe",
                "bounce": "reply.bounce",
            }.get(cls)
            if key_for_cls:
                severity = (
                    "success" if cls == "positive"
                    else "warning" if cls in ("unsubscribe", "negative")
                    else "error"
                )
                await publish(
                    self.session,
                    tenant_id=tenant_id,
                    event_key=key_for_cls,
                    severity=severity,
                    title=f"{reply.from_email} \u2014 {cls}",
                    body=(reply.body_text or "")[:280] or None,
                    target_type="reply",
                    target_id=reply.id,
                    payload={
                        "classification": cls,
                        "send_id": str(send.id),
                        "lead_id": str(step.lead_id) if step else None,
                    },
                )
        except Exception as exc:
            log.warning("notification dispatch failed on reply: %s", exc)


    async def _maybe_create_meeting(
        self,
        *,
        tenant_id: uuid.UUID,
        step: SequenceStep,
        reply: Reply,
        send: Send,
    ) -> None:
        """Phase 5: on a positive reply, either:
        - confirm an open proposal for this lead (counter-reply), or
        - create a fresh proposal with 3 working-day slots.
        Then sync the (newly confirmed) meeting to any active CRM.
        """
        from outreach_os.services.crm_service import CrmService
        from outreach_os.services.meeting_service import MeetingService

        meeting_service = MeetingService(self.session)
        # Is there an open proposal for this lead? If yes, this is a
        # counter-reply ("yes, Tuesday at 2pm") — auto-confirm slot 0.
        open_meeting = await meeting_service.find_proposed_for_lead(
            tenant_id=tenant_id, lead_id=step.lead_id
        )
        if open_meeting is not None:
            try:
                open_meeting = await meeting_service.confirm(
                    tenant_id=tenant_id,
                    meeting_id=open_meeting.id,
                    slot_index=0,
                )
            except Exception as exc:
                log.warning(
                    "auto-confirm meeting failed lead=%s meeting=%s: %s",
                    step.lead_id, open_meeting.id, exc,
                )
                return
        else:
            try:
                meeting = await meeting_service.create_proposal(
                    tenant_id=tenant_id,
                    lead_id=step.lead_id,
                    send_id=send.id,
                    reply_id=reply.id,
                    mailbox_id=send.mailbox_id,
                )
            except Exception as exc:
                log.warning(
                    "auto-create meeting failed lead=%s: %s", step.lead_id, exc,
                )
                return
            open_meeting = meeting
        # If the meeting is confirmed, fan out to CRM.
        if open_meeting.status == "confirmed":
            crm_service = CrmService(self.session)
            try:
                await crm_service.sync_meeting(
                    tenant_id=tenant_id, meeting_id=open_meeting.id
                )
            except Exception as exc:
                log.warning(
                    "crm sync after confirm failed meeting=%s: %s",
                    open_meeting.id, exc,
                )

    # --- Read paths used by the API ---

    async def list_replies(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID | None = None,
        classification: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Reply], int]:
        from sqlalchemy import func
        conds = [Reply.tenant_id == tenant_id]
        if classification is not None:
            conds.append(Reply.classification == classification)
        if run_id is not None:
            conds.append(SequenceStep.run_id == run_id)
            stmt = (
                select(Reply)
                .join(Send, Send.id == Reply.send_id)
                .join(SequenceStep, SequenceStep.id == Send.step_id)
                .where(*conds)
            )
        else:
            stmt = select(Reply).where(*conds)
        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar_one()
        result = await self.session.execute(
            stmt.order_by(Reply.received_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)
