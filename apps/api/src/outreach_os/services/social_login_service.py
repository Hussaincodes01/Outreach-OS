"""Turn a verified social identity into a session.

Three cases, and the distinction between them is the whole security surface:

1. Known subject      -> sign that user in.
2. Known email        -> LINK the provider to the existing account, but only
                         if the provider says the address is verified.
3. Neither            -> provision a new workspace.

Case 2 is where account takeover lives. If we linked on an unverified address,
anyone able to create an account at an identity provider claiming
victim@company.com would inherit that workspace. So an unverified address is
refused rather than linked.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.audit import write_audit_event
from outreach_os.core.auth import hash_password
from outreach_os.core.errors import AuthError
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.user import AppUser, UserRole
from outreach_os.services import tenant_service
from outreach_os.services.social_auth import SocialIdentity

log = logging.getLogger(__name__)


def _unusable_password_hash() -> str:
    """A hash no password can produce.

    SSO accounts must not be sign-in-able with a password, but the column is
    NOT NULL by design — a nullable hash invites a comparison bug where empty
    matches everything.
    """
    return hash_password(secrets.token_urlsafe(48))


def _workspace_name(identity: SocialIdentity) -> str:
    """Name the new workspace after the company, not the person.

    A B2B tool is shared, so "Acme" reads better than "dana@acme.com" for
    everyone who joins later.
    """
    domain = identity.email.split("@", 1)[-1]
    generic = {
        "gmail.com", "googlemail.com", "outlook.com", "hotmail.com",
        "live.com", "yahoo.com", "icloud.com", "proton.me", "protonmail.com",
    }
    if domain and domain not in generic:
        return domain.split(".")[0].replace("-", " ").title()
    if identity.full_name:
        return f"{identity.full_name}'s workspace"
    return f"{identity.email.split('@')[0]}'s workspace"


async def _locate(
    session: AsyncSession, sql: str, params: dict[str, str]
) -> uuid.UUID | None:
    """Cross-tenant lookup via a SECURITY DEFINER helper.

    A plain SELECT cannot work here: at this point in the flow no tenant is
    known, so there is no `app.current_tenant` GUC and RLS filters every row
    away — the query would report "no such user" for everyone and we would
    create a duplicate account on every single sign-in.
    """
    row = (await session.execute(text(sql), params)).first()
    if row is None:
        return None
    return uuid.UUID(str(row.tenant_id))


async def _load_in_tenant(
    session: AsyncSession, tenant_id: uuid.UUID, **criteria: str
) -> AppUser | None:
    """Re-read the user with RLS bound, so the ORM object is tenant-scoped."""
    await set_tenant_for_session(session, str(tenant_id))
    stmt = select(AppUser).where(AppUser.tenant_id == tenant_id)
    if "subject" in criteria:
        stmt = stmt.where(
            AppUser.auth_provider == criteria["provider"],
            AppUser.auth_subject == criteria["subject"],
        )
    else:
        stmt = stmt.where(AppUser.email == criteria["email"].lower())
    return (await session.execute(stmt)).scalar_one_or_none()


async def sign_in_or_provision(
    session: AsyncSession, identity: SocialIdentity
) -> tuple[AppUser, bool]:
    """Return (user, created). Session must NOT be RLS-bound on entry.

    Runs before a tenant is known, so it needs a session that can see across
    tenants — the caller supplies an unscoped one and this function binds the
    GUC as soon as the tenant is resolved.
    """
    subject_tenant = await _locate(
        session,
        "SELECT * FROM auth_user_by_subject(:provider, :subject)",
        {"provider": identity.provider, "subject": identity.subject},
    )
    if subject_tenant is not None:
        existing = await _load_in_tenant(
            session,
            subject_tenant,
            provider=identity.provider,
            subject=identity.subject,
        )
        if existing is None:
            raise AuthError("this account is no longer available")
        if not existing.is_active:
            raise AuthError("this account has been deactivated")
        return existing, False

    email_tenant = await _locate(
        session,
        "SELECT * FROM auth_user_for_linking(:email)",
        {"email": identity.email},
    )
    if email_tenant is not None:
        by_email = await _load_in_tenant(session, email_tenant, email=identity.email)
    else:
        by_email = None
    if by_email is not None:
        if not identity.email_verified:
            # The provider will not vouch for this address, so linking it to an
            # existing workspace would let anyone who can register that address
            # at the provider take the account over.
            raise AuthError(
                f"{identity.provider.title()} has not verified {identity.email}. "
                "Sign in with your password instead."
            )
        if not by_email.is_active:
            raise AuthError("this account has been deactivated")
        # Link rather than duplicate: the person already has this workspace.
        by_email.auth_provider = identity.provider
        by_email.auth_subject = identity.subject
        if by_email.email_verified_at is None:
            by_email.email_verified_at = datetime.now(timezone.utc)
        await session.flush()
        await write_audit_event(
            session,
            action="user.social_account_linked",
            target_type="user",
            target_id=by_email.id,
            actor_kind="user",
            actor_id=by_email.id,
            payload={"provider": identity.provider},
        )
        return by_email, False

    # Nobody matches — provision a workspace with this person as owner.
    tenant_id = uuid.uuid4()
    await set_tenant_for_session(session, str(tenant_id))
    tenant = await tenant_service.create_tenant(
        session, name=_workspace_name(identity), slug=None, tenant_id=tenant_id
    )
    user = AppUser(
        tenant_id=tenant.id,
        email=identity.email,
        password_hash=_unusable_password_hash(),
        role=UserRole.OWNER.value,
        auth_provider=identity.provider,
        auth_subject=identity.subject,
        # The provider already confirmed it; asking again would be theatre.
        email_verified_at=(
            datetime.now(timezone.utc) if identity.email_verified else None
        ),
    )
    session.add(user)
    await session.flush()

    await write_audit_event(
        session,
        action="tenant.created",
        target_type="tenant",
        target_id=tenant.id,
        actor_kind="system",
        payload={"name": tenant.name, "slug": tenant.slug, "via": identity.provider},
    )
    await write_audit_event(
        session,
        action="user.signed_up",
        target_type="user",
        target_id=user.id,
        actor_kind="user",
        actor_id=user.id,
        payload={"provider": identity.provider},
    )
    return user, True


__all__ = ["sign_in_or_provision"]
