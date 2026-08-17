"""Auth schemas."""
from __future__ import annotations

import uuid

from pydantic import EmailStr, Field

from outreach_os.domain.schemas.common import ApiModel


class SignupRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    tenant_name: str = Field(min_length=1, max_length=200)
    tenant_slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=63,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
        description="Optional. If omitted, derived from tenant_name.",
    )


class LoginRequest(ApiModel):
    email: EmailStr
    password: str


class TokenPair(ApiModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: uuid.UUID
    tenant_id: uuid.UUID


class RefreshRequest(ApiModel):
    refresh_token: str


class AccessTokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ForgotPasswordRequest(ApiModel):
    email: EmailStr


class ResetPasswordRequest(ApiModel):
    token: str = Field(min_length=1)
    # Same floor as signup; a reset must not be a way to weaken a password.
    new_password: str = Field(min_length=12, max_length=200)


class VerifyEmailRequest(ApiModel):
    token: str = Field(min_length=1)


class SimpleMessage(ApiModel):
    """Deliberately uninformative for account-enumeration-sensitive endpoints."""

    message: str


class SocialProviderOut(ApiModel):
    """A sign-in provider this deployment has credentials for."""

    provider: str
    label: str


class AuthContext(ApiModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
