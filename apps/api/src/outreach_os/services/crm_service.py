"""CrmService \u2014 CRUD for CRM connections + sync one meeting to all
active connections for the tenant.

`sync_meeting` is the heart of the Phase 5 exit criterion: when a meeting
is confirmed, we look up every active CrmConnection for the tenant, mint
an access token from the linked credential, build a CrmRow from the
meeting + lead, and call `CrmClient.append_row` on each. Every attempt
\u2014 success or failure \u2014 is recorded as a CrmSyncEvent for audit.

The OAuth scope we request is just spreadsheets (`.../auth/spreadsheets`)
since we only write rows in V1. When Phase 6+ adds read/poll we'll
add the calendar scope too.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.config import get_settings
from outreach_os.core.crm_client import (
    CrmClient,
    CrmError,
    CrmRow,
    get_crm_client,
)
from outreach_os.domain.models.credential import Credential
from outreach_os.domain.models.crm_connection import CrmConnection
from outreach_os.domain.models.crm_sync_event import CrmSyncEvent
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.meeting import Meeting
from outreach_os.services import vault_service

log = logging.getLogger(__name__)


class CrmServiceError(RuntimeError):
    pass


class CrmService:
    def __init__(
        self,
        session: AsyncSession,
        crm_client: CrmClient | None = None,
    ) -> None:
        self.session = session
        self.crm_client = crm_client or get_crm_client()
        self.settings = get_settings()

    # ------------------------------------------------------------------ #
    # Connection CRUD
    # ------------------------------------------------------------------ #

    async def create_connection(
        self,
        *,
        tenant_id: uuid.UUID,
        provider: str,
        name: str,
        spreadsheet_id: str | None,
        sheet_range: str | None,
        column_mapping: dict[str, str],
        access_token_credential_id: uuid.UUID | None,
    ) -> CrmConnection:
        if provider not in self.settings.crm_supported_providers:
            raise CrmServiceError(
                f"unsupported provider: {provider!r}; supported: "
                f"{self.settings.crm_supported_providers}"
            )
        conn = CrmConnection(
            tenant_id=tenant_id,
            provider=provider,
            name=name,
            spreadsheet_id=spreadsheet_id,
            sheet_range=sheet_range or "A:Z",
            column_mapping=column_mapping,
            access_token_credential_id=access_token_credential_id,
            status="active",
        )
        self.session.add(conn)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise CrmServiceError(
                f"connection name already exists for this tenant: {name!r}"
            ) from exc
        return conn

    async def update_connection(
        self,
        *,
        tenant_id: uuid.UUID,
        connection_id: uuid.UUID,
        name: str | None = None,
        spreadsheet_id: str | None = None,
        sheet_range: str | None = None,
        column_mapping: dict[str, str] | None = None,
        status: str | None = None,
    ) -> CrmConnection | None:
        conn = await self.get_connection(
            tenant_id=tenant_id, connection_id=connection_id
        )
        if conn is None:
            return None
        if name is not None:
            conn.name = name
        if spreadsheet_id is not None:
            conn.spreadsheet_id = spreadsheet_id
        if sheet_range is not None:
            conn.sheet_range = sheet_range
        if column_mapping is not None:
            conn.column_mapping = column_mapping
        if status is not None:
            if status not in ("active", "paused", "error"):
                raise CrmServiceError(f"invalid status: {status!r}")
            conn.status = status
        await self.session.flush()
        return conn

    async def delete_connection(
        self, *, tenant_id: uuid.UUID, connection_id: uuid.UUID
    ) -> bool:
        conn = await self.get_connection(
            tenant_id=tenant_id, connection_id=connection_id
        )
        if conn is None:
            return False
        await self.session.delete(conn)
        await self.session.flush()
        return True

    async def get_connection(
        self, *, tenant_id: uuid.UUID, connection_id: uuid.UUID
    ) -> CrmConnection | None:
        return (
            await self.session.execute(
                select(CrmConnection).where(
                    CrmConnection.tenant_id == tenant_id,
                    CrmConnection.id == connection_id,
                )
            )
        ).scalar_one_or_none()

    async def list_connections(
        self,
        *,
        tenant_id: uuid.UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[CrmConnection], int]:
        stmt = select(CrmConnection).where(CrmConnection.tenant_id == tenant_id)
        count_stmt = select(func.count()).select_from(CrmConnection).where(
            CrmConnection.tenant_id == tenant_id
        )
        if status:
            stmt = stmt.where(CrmConnection.status == status)
            count_stmt = count_stmt.where(CrmConnection.status == status)
        total = (await self.session.execute(count_stmt)).scalar_one()
        items = (
            await self.session.execute(
                stmt.order_by(CrmConnection.created_at.desc())
                .limit(limit).offset(offset)
            )
        ).scalars().all()
        return items, int(total)

    # ------------------------------------------------------------------ #
    # Sync
    # ------------------------------------------------------------------ #

    async def sync_meeting(
        self, *, tenant_id: uuid.UUID, meeting_id: uuid.UUID
    ) -> list[CrmSyncEvent]:
        """Push a confirmed meeting to every active CrmConnection for
        the tenant. Returns the list of CrmSyncEvent rows (one per
        connection, success or failure)."""
        # Phase 7: gate CRM sync behind the plan's feature flag.
        from outreach_os.services.billing_service import (
            BillingError,
            effective_plan,
        )
        plan = await effective_plan(self.session, tenant_id=tenant_id)
        if not plan.crm_sync_enabled:
            raise BillingError(
                f"CRM sync requires a {plan.code or 'higher'} plan; "
                f"upgrade to growth or above to push meetings to your CRM."
            )
        meeting = await self._load_meeting(tenant_id, meeting_id)
        conns = (await self.session.execute(
            select(CrmConnection).where(
                CrmConnection.tenant_id == tenant_id,
                CrmConnection.status == "active",
            )
        )).scalars().all()
        if not conns:
            log.info("crm.sync_meeting tenant=%s meeting=%s: no active connections",
                     tenant_id, meeting_id)
            return []
        lead = (await self.session.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id, Lead.id == meeting.lead_id
            )
        )).scalar_one_or_none()
        events: list[CrmSyncEvent] = []
        for conn in conns:
            events.append(await self._sync_one(tenant_id, conn, meeting, lead))
        return events

    async def _load_meeting(
        self, tenant_id: uuid.UUID, meeting_id: uuid.UUID
    ) -> Meeting:
        meeting = (
            await self.session.execute(
                select(Meeting).where(
                    Meeting.tenant_id == tenant_id, Meeting.id == meeting_id
                )
            )
        ).scalar_one_or_none()
        if meeting is None:
            raise CrmServiceError(
                f"meeting {meeting_id} not found for tenant {tenant_id}"
            )
        return meeting

    async def list_sync_events(
        self,
        *,
        tenant_id: uuid.UUID,
        connection_id: uuid.UUID | None = None,
        meeting_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[CrmSyncEvent], int]:
        stmt = select(CrmSyncEvent).where(CrmSyncEvent.tenant_id == tenant_id)
        count_stmt = select(func.count()).select_from(CrmSyncEvent).where(
            CrmSyncEvent.tenant_id == tenant_id
        )
        if connection_id:
            stmt = stmt.where(CrmSyncEvent.crm_connection_id == connection_id)
            count_stmt = count_stmt.where(
                CrmSyncEvent.crm_connection_id == connection_id
            )
        if meeting_id:
            stmt = stmt.where(CrmSyncEvent.meeting_id == meeting_id)
            count_stmt = count_stmt.where(CrmSyncEvent.meeting_id == meeting_id)
        total = (await self.session.execute(count_stmt)).scalar_one()
        items = (
            await self.session.execute(
                stmt.order_by(CrmSyncEvent.synced_at.desc())
                .limit(limit).offset(offset)
            )
        ).scalars().all()
        return items, int(total)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _sync_one(
        self,
        tenant_id: uuid.UUID,
        conn: CrmConnection,
        meeting: Meeting,
        lead: Lead | None,
    ) -> CrmSyncEvent:
        # Phase 7: gate CRM sync behind the plan's feature flag.
        from outreach_os.services.billing_service import (
            BillingError,
            effective_plan,
        )
        plan = await effective_plan(self.session, tenant_id=tenant_id)
        if not plan.crm_sync_enabled:
            raise BillingError(
                f"CRM sync requires a {plan.code or 'higher'} plan; "
                f"upgrade to growth or above to push meetings to your CRM."
            )
        event = CrmSyncEvent(
            tenant_id=tenant_id,
            crm_connection_id=conn.id,
            meeting_id=meeting.id,
            status="failed",
        )
        try:
            access_token = await self._mint_access_token(tenant_id, conn)
            row = self._build_row(meeting, lead, conn)
            result = self.crm_client.append_row(
                spreadsheet_id=conn.spreadsheet_id or "",
                sheet_range=conn.sheet_range or "A:Z",
                column_mapping=dict(conn.column_mapping or {}),
                row=row,
                access_token=access_token,
            )
            event.status = "success"
            event.row_written = dict(result.raw) if result.raw else {
                "external_id": result.external_id,
                "values": [row.fields.get(k) for k in (conn.column_mapping or {})],
            }
            conn.last_sync_at = datetime.now(timezone.utc)
            conn.last_sync_error = None
        except CrmError as exc:
            log.warning("crm sync failed conn=%s: %s", conn.id, exc)
            event.error = str(exc)
            conn.last_sync_at = datetime.now(timezone.utc)
            conn.last_sync_error = str(exc)
            conn.status = "error"
        except Exception as exc:
            log.exception("crm sync unexpected error conn=%s", conn.id)
            event.error = f"unexpected: {exc}"
            conn.last_sync_at = datetime.now(timezone.utc)
            conn.last_sync_error = str(exc)
            conn.status = "error"
        self.session.add(event)
        await self.session.flush()

        # Phase 6: surface CRM sync failure as a notification.
        if event.status == "failed":
            try:
                from outreach_os.services.notification_service import publish

                await publish(
                    self.session,
                    tenant_id=tenant_id,
                    event_key="crm.sync.failed",
                    severity="error",
                    title=f"CRM sync failed: {conn.name}",
                    body=(event.error or "")[:280],
                    target_type="crm_connection",
                    target_id=conn.id,
                    payload={
                        "meeting_id": str(meeting.id),
                        "error": event.error,
                    },
                )
            except Exception:
                log.warning("notification dispatch failed for crm.sync.failed", exc_info=True)

        return event

    async def _mint_access_token(
        self, tenant_id: uuid.UUID, conn: CrmConnection
    ) -> str:
        """Pull the OAuth access token from the connection's credential
        row. We don't refresh in V1 — tokens are minted at OAuth time
        and we expect them to be valid for the demo / first sync.

        If the connection has no credential_id, return an empty string so
        the StubCrmClient (which doesn't check the token) can still run.
        """
        if conn.access_token_credential_id is None:
            return ""
        cred = (await self.session.execute(
            select(Credential).where(
                Credential.tenant_id == tenant_id,
                Credential.id == conn.access_token_credential_id,
            )
        )).scalar_one_or_none()
        if cred is None:
            return ""
        try:
            payload = vault_service.decrypt_for_tenant(
                str(tenant_id), cred.ciphertext
            )
        except Exception as exc:
            raise CrmError(f"failed to decrypt CRM credential: {exc}") from exc
        token = (
            payload.get("access_token")
            or payload.get("token")
            or payload.get("api_key")
            or ""
        )
        return str(token)

    @staticmethod
    def _build_row(
        meeting: Meeting, lead: Lead | None, conn: CrmConnection
    ) -> CrmRow:
        """Build a CrmRow from the meeting + lead fields.

        Field defaults are Outreach OS names: first_name, last_name,
        full_name, email, company_name, title, meeting_subject,
        meeting_start, meeting_end, meeting_status, meeting_ics_uid.
        The connection's `column_mapping` is what selects which fields
        get written to which columns.
        """
        chosen = meeting.chosen_slot.isoformat() if meeting.chosen_slot else ""
        # Duration-based end: chosen_slot + duration_minutes.
        end_iso = ""
        if meeting.chosen_slot is not None:
            from datetime import timedelta
            end_iso = (meeting.chosen_slot + timedelta(minutes=meeting.duration_minutes)).isoformat()
        fields: dict[str, Any] = {
            "first_name": lead.first_name if lead else "",
            "last_name": lead.last_name if lead else "",
            "full_name": (lead.full_name if lead else "") or (
                f"{lead.first_name or ''} {lead.last_name or ''}".strip() if lead else ""
            ),
            "email": lead.email if lead else meeting.attendee_email,
            "company_name": lead.company_name if lead else "",
            "title": lead.title if lead else "",
            "meeting_subject": meeting.subject,
            "meeting_start": chosen,
            "meeting_end": end_iso,
            "meeting_status": meeting.status,
            "meeting_ics_uid": meeting.ics_uid,
        }
        return CrmRow(fields=fields)


__all__ = ["CrmService", "CrmServiceError"]
