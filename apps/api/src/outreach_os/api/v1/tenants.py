"""Tenant endpoints — read/update the caller's own tenant."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.domain.schemas.tenant import TenantOut, TenantUpdate
from outreach_os.services import tenant_service

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/me", response_model=TenantOut)
async def get_my_tenant(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> TenantOut:
    tenant = await tenant_service.get_tenant(db, user.tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found"
        )
    return TenantOut.model_validate(tenant)


@router.patch("/me", response_model=TenantOut)
async def update_my_tenant(
    payload: TenantUpdate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> TenantOut:
    tenant = await tenant_service.get_tenant(db, user.tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found"
        )
    if user.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role"
        )

    if payload.name is not None:
        tenant.name = payload.name
    await write_audit_event(
        db,
        action="tenant.updated",
        target_type="tenant",
        target_id=tenant.id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"name": tenant.name},
    )
    return TenantOut.model_validate(tenant)
