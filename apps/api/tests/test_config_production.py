"""Production configuration parsing and fail-fast validation.

These run against real environment variables, which is the only way to catch
the class of bug this file exists for: pydantic-settings parses complex field
types inside `EnvSettingsSource`, BEFORE any field validator runs. A
`mode="before"` validator that looks correct in isolation can therefore never
execute, and the failure only appears when the app is deployed.
"""
from __future__ import annotations

import base64
import secrets

import pytest
from pydantic import ValidationError

from outreach_os.core.config import Settings

_STRONG_SECRET = secrets.token_hex(32)
_VAULT_KEY = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def _prod_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    env = {
        "ENVIRONMENT": "production",
        "VAULT_MASTER_KEY": _VAULT_KEY,
        "INBOUND_WEBHOOK_SECRET": _STRONG_SECRET,
        "CORS_ALLOWED_ORIGINS": "https://app.example.com",
        "PUBLIC_BASE_URL": "https://api.example.com",
        "CELERY_TASK_ALWAYS_EAGER": "false",
        "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/x",
    }
    env.update(overrides)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


# --- CORS parsing -----------------------------------------------------------


def test_comma_separated_cors_origins_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """The format `.env.production.example` documents.

    Regression: this previously raised SettingsError from EnvSettingsSource
    (json.loads on a bare URL), so a correctly-followed production config made
    the API refuse to start.
    """
    _prod_env(
        monkeypatch,
        CORS_ALLOWED_ORIGINS="https://app.example.com, https://admin.example.com",
    )
    settings = Settings()
    assert settings.cors_allowed_origins == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_single_cors_origin_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_env(monkeypatch, CORS_ALLOWED_ORIGINS="https://app.example.com")
    assert Settings().cors_allowed_origins == ["https://app.example.com"]


def test_json_array_cors_origins_still_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backwards compatibility for anyone already using the JSON form."""
    _prod_env(
        monkeypatch,
        CORS_ALLOWED_ORIGINS='["https://app.example.com","https://b.example.com"]',
    )
    assert Settings().cors_allowed_origins == [
        "https://app.example.com",
        "https://b.example.com",
    ]


def test_malformed_json_cors_gives_a_readable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prod_env(monkeypatch, CORS_ALLOWED_ORIGINS='["https://a.example.com"')
    with pytest.raises(ValidationError, match="looks like JSON but is not valid"):
        Settings()


# --- fail-fast production safety -------------------------------------------


def test_production_boots_with_a_complete_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prod_env(monkeypatch)
    settings = Settings()
    assert settings.environment == "production"
    assert settings.celery_task_always_eager is False


def test_missing_cors_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without it the deployed web app cannot call the API at all."""
    _prod_env(monkeypatch, CORS_ALLOWED_ORIGINS="")
    with pytest.raises(ValidationError, match="CORS_ALLOWED_ORIGINS"):
        Settings()


def test_localhost_public_base_url_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tracking pixels and unsubscribe links would point at the container."""
    _prod_env(monkeypatch, PUBLIC_BASE_URL="http://localhost:8000")
    with pytest.raises(ValidationError, match="PUBLIC_BASE_URL"):
        Settings()


def test_eager_celery_is_refused_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eager mode would run every background job inside the web request."""
    _prod_env(monkeypatch, CELERY_TASK_ALWAYS_EAGER="true")
    with pytest.raises(ValidationError, match="CELERY_TASK_ALWAYS_EAGER"):
        Settings()


def test_short_vault_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_env(
        monkeypatch,
        VAULT_MASTER_KEY=base64.urlsafe_b64encode(secrets.token_bytes(8)).decode(),
    )
    with pytest.raises(ValidationError, match="VAULT_MASTER_KEY"):
        Settings()
