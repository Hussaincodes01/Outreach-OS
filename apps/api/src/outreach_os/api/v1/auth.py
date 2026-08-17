"""Auth endpoints: signup, login, refresh, me."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import get_current_user, get_db, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.core.auth import (
    TokenError,
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    create_refresh_token,
    decode_email_verification_token,
    decode_password_reset_token,
    decode_token,
    hash_password,
    verify_password,
)
from outreach_os.core.config import Settings
from outreach_os.core.rate_limit import RateLimitDecision, check_and_consume_ip
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.user import AppUser, UserRole
from outreach_os.domain.schemas.auth import (
    AccessTokenResponse,
    AuthContext,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    SignupRequest,
    SimpleMessage,
    TokenPair,
    VerifyEmailRequest,
)
from outreach_os.domain.schemas.user import UserOut
from outreach_os.services import account_email, tenant_service, user_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _settings() -> Settings:
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

    # Best-effort: a mail outage must not block signup. The user lands in the
    # app either way and can re-request the link from the banner.
    verification = create_email_verification_token(
        user_id=str(user.id), tenant_id=str(tenant.id), email=user.email
    )
    await asyncio.to_thread(
        account_email.send_email_verification,
        to_email=user.email,
        token=verification,
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


@router.post(
    "/forgot-password",
    response_model=SimpleMessage,
    status_code=status.HTTP_202_ACCEPTED,
)
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> SimpleMessage:
    """Email a password-reset link.

    Always returns the same 202, whether or not the address exists. Anything
    else turns this endpoint into an account-enumeration oracle: an attacker
    could discover exactly who has an account by watching status codes or
    response times.
    """
    decision = _rate_limit(request, "password_reset")
    if not decision.allowed:
        _raise_429(decision)

    found = await user_service.lookup_user_by_email(db, payload.email)
    if found is not None:
        tenant_id, user_id, password_hash, _role = found
        token = create_password_reset_token(
            user_id=str(user_id),
            tenant_id=str(tenant_id),
            password_hash=password_hash,
        )
        await set_tenant_for_session(db, str(tenant_id))
        await write_audit_event(
            db,
            action="user.password_reset_requested",
            target_type="user",
            target_id=user_id,
            actor_kind="user",
            actor_id=user_id,
        )
        # Off the event loop: SMTP is blocking and a slow relay would
        # otherwise make "address exists" measurable by response time.
        await asyncio.to_thread(
            account_email.send_password_reset, to_email=payload.email, token=token
        )

    return SimpleMessage(
        message="If that address has an account, a reset link is on its way."
    )


@router.post("/reset-password", response_model=SimpleMessage)
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> SimpleMessage:
    """Set a new password using a reset token.

    The token embeds a fingerprint of the current password hash, so completing
    a reset invalidates the link — and any other outstanding links.
    """
    decision = _rate_limit(request, "password_reset")
    if not decision.allowed:
        _raise_429(decision)

    try:
        unverified = decode_token(payload.token, expected_type="password_reset")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    tenant_id = uuid.UUID(str(unverified["tid"]))
    user_id = uuid.UUID(str(unverified["sub"]))
    await set_tenant_for_session(db, str(tenant_id))

    user = await db.get(AppUser, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid reset link"
        )

    # Re-check against the stored hash: this is what enforces single use.
    try:
        decode_password_reset_token(payload.token, password_hash=user.password_hash)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    user.password_hash = hash_password(payload.new_password)
    await db.flush()
    await write_audit_event(
        db,
        action="user.password_reset_completed",
        target_type="user",
        target_id=user.id,
        actor_kind="user",
        actor_id=user.id,
    )
    return SimpleMessage(message="Your password has been changed. You can sign in now.")


@router.post("/verify-email", response_model=SimpleMessage)
async def verify_email(
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
) -> SimpleMessage:
    """Confirm an email address from a verification link."""
    try:
        unverified = decode_token(payload.token, expected_type="email_verify")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    tenant_id = uuid.UUID(str(unverified["tid"]))
    user_id = uuid.UUID(str(unverified["sub"]))
    await set_tenant_for_session(db, str(tenant_id))

    user = await db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid verification link"
        )
    try:
        decode_email_verification_token(payload.token, email=user.email)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        await db.flush()
        await write_audit_event(
            db,
            action="user.email_verified",
            target_type="user",
            target_id=user.id,
            actor_kind="user",
            actor_id=user.id,
        )
    return SimpleMessage(message="Email confirmed.")


@router.post(
    "/resend-verification",
    response_model=SimpleMessage,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resend_verification(
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SimpleMessage:
    """Re-send the confirmation link for the signed-in user."""
    decision = _rate_limit(request, "password_reset")
    if not decision.allowed:
        _raise_429(decision)

    row = await db.get(AppUser, user.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    if row.email_verified_at is not None:
        return SimpleMessage(message="That address is already confirmed.")

    token = create_email_verification_token(
        user_id=str(row.id), tenant_id=str(row.tenant_id), email=row.email
    )
    await asyncio.to_thread(
        account_email.send_email_verification, to_email=row.email, token=token
    )
    return SimpleMessage(message="Confirmation email sent.")


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
