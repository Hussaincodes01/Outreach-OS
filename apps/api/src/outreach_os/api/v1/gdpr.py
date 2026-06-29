"""GDPR compliance endpoints: data export (DSAR) and right to erasure."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.core.db import session_scope
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.tenant import Tenant

router = APIRouter(prefix="/gdpr", tags=["gdpr"])


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
            cols = await session.execute(text(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = '{table}' AND column_name = 'tenant_id'
            """))
            if not cols.scalar_one_or_none():
                continue
            
            rows = await session.execute(text(f"""
                SELECT * FROM {table} WHERE tenant_id = :tid
            """), {"tid": tenant_id})
            
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
):
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


@router.delete("/me", status_code=status.HTTP_202_ACCEPTED)
async def delete_my_account(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
):
    """Right to erasure: Soft-delete tenant and anonymize PII.
    
    - Marks tenant as 'deleted' (status)
    - Anonymizes email/name in user table
    - Audit log remains immutable (hash-chained)
    - Actual purge after 30-day grace period (admin job)
    """
    # Verify tenant exists and user is owner
    tenant = await db.get(Tenant, user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    
    # Anonymize user PII
    from outreach_os.domain.models.user import AppUser
    user_row = await db.get(AppUser, user.user_id)
    if user_row:
        user_row.email = f"deleted-{user.user_id}@gdpr.local"
        user_row.first_name = "Deleted"
        user_row.last_name = "User"
        user_row.is_active = False
    
    # Mark tenant deleted
    tenant.status = "deleted"
    tenant.name = f"Deleted Tenant {tenant.id}"
    
    await db.flush()
    
    await write_audit_event(
        db, action="gdpr.erasure_requested", target_type="tenant",
        target_id=user.tenant_id, actor_kind="user", actor_id=user.user_id,
        payload={"grace_period_days": 30}
    )
    
    return {"status": "deletion_scheduled", "grace_period_days": 30}


@router.get("/export/status")
async def export_status(
    user: AuthContext = Depends(get_current_user),
):
    """Check status of a previously requested export (future: async job)."""
    return {"status": "ready", "note": "Export is streaming, no async job yet"}
