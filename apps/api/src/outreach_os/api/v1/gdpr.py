"""GDPR compliance endpoints: data export (DSAR).

There is deliberately no erasure endpoint in the single-user build. The old
`DELETE /v1/gdpr/me` marked the only workspace's tenant `deleted`, which
silently stopped every sequence send with no way to restore it. To wipe all
data, stop the stack with `docker compose down -v` (see docs/runbook.md).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.core.db import session_scope
from outreach_os.core.tenancy import set_tenant_for_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/gdpr", tags=["gdpr"])

# Postgres unquoted-identifier shape. Guards the one place a table name has to
# be interpolated into SQL (see _stream_tenant_data).
_SAFE_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


async def _stream_tenant_data(tenant_id: uuid.UUID) -> AsyncIterator[bytes]:
    """Stream all tenant data as NDJSON for DSAR export."""
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tenant_id))

        # Get all tables for this tenant
        tables = await session.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name NOT IN ('alembic_version', 'plan')
            AND table_type = 'BASE TABLE'
        """))
        table_names = [row[0] for row in tables.fetchall()]

        for table in table_names:
            # Check if table has tenant_id column
            cols = await session.execute(
                text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = :tbl AND column_name = 'tenant_id'
                """),
                {"tbl": table},
            )
            if not cols.scalar_one_or_none():
                continue

            # A table name cannot be a bind parameter, so it is interpolated.
            # `table` comes from information_schema (never from the request)
            # and is re-validated here before being quoted as an identifier.
            if not _SAFE_IDENT.fullmatch(table):
                log.warning("gdpr export: skipping non-identifier table %r", table)
                continue
            rows = await session.execute(
                text(f'SELECT * FROM "{table}" WHERE tenant_id = :tid'),  # noqa: S608
                {"tid": tenant_id},
            )

            for row in rows.fetchall():
                data = dict(row._mapping)
                # Convert UUIDs and datetimes to strings
                for k, v in data.items():
                    if isinstance(v, (uuid.UUID, datetime)):
                        data[k] = str(v)
                yield (json.dumps({"table": table, "data": data}) + "\n").encode()


@router.get("/export", response_class=StreamingResponse)
async def export_my_data(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> StreamingResponse:
    """DSAR: Export all personal data for the authenticated user's tenant.

    Returns NDJSON stream: each line is {"table": "...", "data": {...}}
    """
    await write_audit_event(
        db, action="gdpr.export_requested", target_type="tenant",
        target_id=user.tenant_id, actor_kind="user", actor_id=user.user_id
    )

    return StreamingResponse(
        _stream_tenant_data(user.tenant_id),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f"attachment; filename=gdpr-export-{user.tenant_id}.ndjson"}
    )


@router.get("/export/status")
async def export_status(
    user: AuthContext = Depends(get_current_user),
) -> dict[str, str]:
    """Check status of a previously requested export (future: async job)."""
    return {"status": "ready", "note": "Export is streaming, no async job yet"}
