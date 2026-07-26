"""User endpoints within a tenant."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.domain.models.user import AppUser
from outreach_os.domain.schemas.user import UserInvite, UserOut
from outreach_os.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[UserOut]:
    result = await db.execute(
        select(AppUser).order_by(AppUser.created_at.asc())
    )
    return [UserOut.model_validate(r) for r in result.scalars().all()]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def invite_user(
    payload: UserInvite,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> UserOut:
    if user.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role"
        )
    existing = await user_service.get_user_by_email(db, user.tenant_id, payload.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already in use"
        )
    from outreach_os.domain.models.user import UserRole

    new_user = await user_service.create_user(
        db,
        tenant_id=user.tenant_id,
        email=payload.email,
        password=payload.password,
        role=UserRole(payload.role),
    )
    await write_audit_event(
        db,
        action="user.invited",
        target_type="user",
        target_id=new_user.id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"email": new_user.email, "role": new_user.role},
    )
    return UserOut.model_validate(new_user)
