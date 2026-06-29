"""Auth endpoints: signup, login, refresh, me."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.audit import write_audit_event
from outreach_os.core.auth import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from outreach_os.core.rate_limit import RateLimitDecision, check_and_consume_ip
from outreach_os.api.deps import get_current_user, get_db, get_scoped_db
from outreach_os.domain.models.user import AppUser, UserRole
from outreach_os.domain.schemas.auth import (
    AccessTokenResponse,
    AuthContext,
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenPair,
)
from outreach_os.domain.schemas.user import UserOut
from outreach_os.services import tenant_service, user_service
from outreach_os.core.tenancy import set_tenant_for_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _settings():
    from outreach_os.core.config import get_settings

    return get_settings()


def _rate_limit(request: Request, source: str) -> RateLimitDecision:
    """Check rate limit for auth endpoint by client IP."""
    client_ip = request.client.host if request.client else "unknown"
    return check_and_consume_ip(client_ip, source)


def _raise_429(decision: RateLimitDecision) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Rate limit exceeded. Try again in {decision.retry_after_seconds}s.",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


@router.post("/signup", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def signup(
    request: Request,
    payload: SignupRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    # Rate limit: 5 signups/min per IP
    decision = _rate_limit(request, "signup")
    if not decision.allowed:
        _raise_429(decision)
    """Create a new tenant + first owner user. Returns access + refresh tokens.

    Flow:
    1. Pre-generate tenant_id (uuid4) so we can bind RLS BEFORE any insert.
    2. Insert tenant row (tenant table is NOT RLS-protected).
    3. Set RLS context to the new tenant_id.
    4. Insert the owner user (RLS-protected; row tenant_id matches GUC).
    5. Write the audit events for tenant.created and user.signed_up.

    Binding RLS first lets the audit-event writer skip the chicken-and-egg
    of needing a tenant row to set the GUC, while needing the GUC to write
    the audit row.
    """
    new_tenant_id = uuid.uuid4()

    # Slug uniqueness check (tenant table has no RLS, runs cleanly).
    if payload.tenant_slug:
        existing_tenant = await tenant_service.get_tenant_by_slug(db, payload.tenant_slug)
        if existing_tenant is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="tenant_slug already in use",
            )

    # Bind RLS to the new tenant FIRST so subsequent writes (user, audit)
    # can be checked against the GUC.
    await set_tenant_for_session(db, str(new_tenant_id))

    tenant = await tenant_service.create_tenant(
        db,
        name=payload.tenant_name,
        slug=payload.tenant_slug,
        tenant_id=new_tenant_id,
    )

    user = await user_service.create_user(
        db,
        tenant_id=tenant.id,
        email=payload.email,
        password=payload.password,
        role=UserRole.OWNER,
    )

    access = create_access_token(
        user_id=str(user.id), tenant_id=str(tenant.id), role=user.role
    )
    refresh = create_refresh_token(
        user_id=str(user.id), tenant_id=str(tenant.id), role=user.role
    )

    await write_audit_event(
        db,
        action="tenant.created",
        target_type="tenant",
        target_id=tenant.id,
        actor_kind="system",
        payload={"name": tenant.name, "slug": tenant.slug, "plan": tenant.plan},
    )
    await write_audit_event(
        db,
        action="user.signed_up",
        target_type="user",
        target_id=user.id,
        actor_kind="user",
        actor_id=user.id,
        payload={"tenant_slug": tenant.slug},
    )

    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=_settings().jwt_access_ttl_minutes * 60,
        user_id=user.id,
        tenant_id=tenant.id,
    )


@router.post("/login", response_model=TokenPair)
async def login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Email + password. The login form posts email + password; we resolve
    the tenant via the SECURITY DEFINER function `auth_user_by_email` (which
    bypasses RLS), then bind the request's RLS context to that tenant for
    any subsequent writes (audit log)."""
    # Rate limit: 10 login attempts/min per IP
    decision = _rate_limit(request, "login")
    if not decision.allowed:
        _raise_429(decision)

    found = await user_service.lookup_user_by_email(db, payload.email)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )
    tenant_id, user_id, password_hash, role = found
    if not verify_password(payload.password, password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )

    # Bind RLS context to the user's tenant so subsequent audit writes
    # and the `get_user_by_email` recheck below are filtered correctly.
    await set_tenant_for_session(db, str(tenant_id))

    # Look up the user object (under RLS, so we get a clean 404 if it was
    # somehow deleted between the cross-tenant lookup and now).
    user = await user_service.get_user_by_email(db, tenant_id, payload.email)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )

    access = create_access_token(
        user_id=str(user_id), tenant_id=str(tenant_id), role=role
    )
    refresh = create_refresh_token(
        user_id=str(user_id), tenant_id=str(tenant_id), role=role
    )

    await write_audit_event(
        db,
        action="user.login",
        target_type="user",
        target_id=user_id,
        actor_kind="user",
        actor_id=user_id,
    )

    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=_settings().jwt_access_ttl_minutes * 60,
        user_id=user_id,
        tenant_id=tenant_id,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    payload: RefreshRequest,
) -> AccessTokenResponse:
    # Rate limit: 30 refreshes/min per IP
    decision = _rate_limit(request, "refresh")
    if not decision.allowed:
        _raise_429(decision)

    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    access = create_access_token(
        user_id=str(claims["sub"]),
        tenant_id=str(claims["tid"]),
        role=str(claims.get("role", "member")),
    )
    return AccessTokenResponse(
        access_token=access, expires_in=_settings().jwt_access_ttl_minutes * 60
    )


@router.get("/me", response_model=UserOut)
async def me(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> UserOut:
    """Return the authenticated user's profile. Uses get_scoped_db so the
    RLS-bound session can find the user row by id."""
    result = await db.execute(select(AppUser).where(AppUser.id == user.user_id))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )
    return UserOut.model_validate(record)
