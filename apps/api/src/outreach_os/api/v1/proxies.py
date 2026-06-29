"""Per-tenant proxy config endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.core.errors import ConflictError, ValidationError
from outreach_os.domain.schemas.lead_scraping import ProxyCreate, ProxyOut
from outreach_os.services import proxy_service

router = APIRouter(prefix="/proxies", tags=["proxies"])


@router.get("", response_model=list[ProxyOut])
async def list_proxies(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[ProxyOut]:
    rows = await proxy_service.list_proxies(db, tenant_id=user.tenant_id)
    return [ProxyOut.model_validate(r) for r in rows]


@router.post("", response_model=ProxyOut, status_code=status.HTTP_201_CREATED)
async def create_proxy(
    payload: ProxyCreate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> ProxyOut:
    try:
        row = await proxy_service.create_proxy(
            db,
            tenant_id=user.tenant_id,
            label=payload.label,
            protocol=payload.protocol,
            host=payload.host,
            port=payload.port,
            url=payload.url,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await write_audit_event(
        db,
        action="proxy.created",
        target_type="proxy",
        target_id=row.id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"label": row.label, "host": row.host, "port": row.port},
    )
    return ProxyOut.model_validate(row)


@router.delete("/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy(
    proxy_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    ok = await proxy_service.delete_proxy(
        db, tenant_id=user.tenant_id, proxy_id=proxy_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="proxy not found")
    await write_audit_event(
        db,
        action="proxy.deleted",
        target_type="proxy",
        target_id=proxy_id,
        actor_kind="user",
        actor_id=user.user_id,
    )
