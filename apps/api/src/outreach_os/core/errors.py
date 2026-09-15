"""Centralised error types so the API layer can map them to HTTP responses."""
from __future__ import annotations


class OutreachError(Exception):
    """Base error."""


class NotFoundError(OutreachError):
    pass


class ValidationError(OutreachError):
    pass


class MailError(OutreachError):
    pass


class ConflictError(OutreachError):
    pass


class SetupRequiredError(OutreachError):
    """The tenant must finish a configuration step before this can work.

    Distinct from ValidationError: the request was well-formed, the workspace
    just isn't set up yet (e.g. no BYOK LLM key connected). Mapped to 428 so
    the web app can send the user to onboarding instead of showing a generic
    failure.
    """
