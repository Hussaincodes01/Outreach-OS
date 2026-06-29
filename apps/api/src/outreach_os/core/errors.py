"""Centralised error types so the API layer can map them to HTTP responses."""
from __future__ import annotations


class OutreachError(Exception):
    """Base error."""


class NotFoundError(OutreachError):
    pass


class AuthError(OutreachError):
    pass


class ValidationError(OutreachError):
    pass


class OAuthError(OutreachError):
    pass


class MailError(OutreachError):
    pass


class ConflictError(OutreachError):
    pass
