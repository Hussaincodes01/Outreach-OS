"""Test fixtures.

Tests REQUIRE a running Postgres reachable via TEST_DATABASE_URL (or
DATABASE_URL when unset). Migrations are applied once per session;
tables are truncated between tests. The DB is NOT destroyed at session
end — we reuse it.
"""
from __future__ import annotations

import os

# --- Configure env BEFORE importing the app ----------------------------
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://outreach:outreach@localhost:5433/outreach_test",
)
os.environ.setdefault(
    "TEST_DATABASE_URL",
    os.environ["DATABASE_URL"],
)
# Migrations need the bootstrap superuser. The app itself still uses DATABASE_URL
# above (the non-superuser) so RLS is enforced under test.
os.environ.setdefault(
    "DATABASE_URL_ADMIN",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/outreach_test",
)
os.environ.setdefault("VAULT_MASTER_KEY", "2QU3n0T0Q3n0T0Q3n0T0Q3n0T0Q3n0T0Q3n0T0Q3n0Q=")
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/15")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6380/15")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6380/15")
# Run Celery tasks synchronously in-process so tests don't need a worker.
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
# Every test shares one client IP, so the production webhook limit would make
# the suite fail on volume rather than behaviour.
os.environ.setdefault("AUTH_RATE_LIMITS_PER_MINUTE", '{"webhook": 10000}')
# Set inbound webhook secret for tests
os.environ.setdefault("INBOUND_WEBHOOK_SECRET", "test-webhook-secret")
# The httpx test client uses base_url="http://test", so its Host header is
# `test`. TrustedHostMiddleware reads this at app import, below.
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1,test")

import uuid as _uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import Header
from sqlalchemy import text

from outreach_os.api.deps import get_current_user
from outreach_os.core import env_keys
from outreach_os.core.audit import write_audit_event
from outreach_os.core.db import dispose_engine, get_engine, get_session_factory, reset_for_tests
from outreach_os.core.mailer import StubMailer, set_mailer_client
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.schemas.auth import AuthContext
from outreach_os.main import app
from outreach_os.services.llm_credentials import NON_LLM_KINDS, PROVIDERS
from outreach_os.services.local_workspace import (
    LOCAL_TENANT_ID,
    ensure_local_workspace,
    local_auth_context,
    reset_local_workspace_cache,
)


async def _test_current_user(x_test_auth: str | None = Header(default=None)) -> AuthContext:
    """Test-only: act as the tenant encoded in X-Test-Auth, else the local workspace.

    Production has no way to pick a tenant; tests need one so they can keep
    proving cross-tenant RLS isolation.
    """
    if not x_test_auth:
        await ensure_local_workspace()
        return local_auth_context()
    tenant_id, user_id, role = x_test_auth.split(":")
    return AuthContext(user_id=_uuid.UUID(user_id), tenant_id=_uuid.UUID(tenant_id), role=role)


app.dependency_overrides[get_current_user] = _test_current_user


@pytest_asyncio.fixture(scope="session", autouse=True)
def _apply_migrations():
    """Apply Alembic migrations once per test session (synchronous,
    run from a worker thread to avoid clashing with the event loop)."""
    from concurrent.futures import ThreadPoolExecutor

    from alembic import command
    from alembic.config import Config

    def _run() -> None:
        # 1) Install extensions as the bootstrap superuser. Extensions like
        #    pgcrypto and vector require SUPERUSER to create. We use a SYNC
        #    driver (psycopg2) here because this runs in a worker thread,
        #    not an asyncio loop. The async app role still uses asyncpg
        #    for runtime queries.
        import sqlalchemy as _sa

        admin_url = os.environ.get("DATABASE_URL_ADMIN", os.environ["DATABASE_URL"])
        sync_admin_url = admin_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
        eng = _sa.create_engine(sync_admin_url)
        with eng.begin() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        eng.dispose()

        # 2) Run the Alembic migration as the ADMIN (superuser) role, exactly
        #    like the `migrate` service in docker-compose.prod.yml. Migration
        #    0010 does `ALTER FUNCTION ... OWNER TO postgres`, which the
        #    non-superuser app role cannot do ("must be able to SET ROLE").
        #    Running as admin also mirrors production ownership: tables are
        #    owned by postgres and the app role reaches them through the
        #    grants in infra/docker/postgres/initdb, so RLS still applies to
        #    the app role (a table owner would bypass it).
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", admin_url)
        command.upgrade(cfg, "head")

    with ThreadPoolExecutor(max_workers=1) as ex:
        ex.submit(_run).result()

    # 3) Fix auth_user_by_email: SECURITY DEFINER needs a superuser owner
    #    to bypass RLS (NOBYPASSRLS roles still hit RLS even under DEFINER).
    #    This is done as admin because ALTER OWNER requires superuser.
    def _fix_auth_function() -> None:
        import sqlalchemy as _sa
        admin_url = os.environ.get("DATABASE_URL_ADMIN", os.environ["DATABASE_URL"])
        sync_admin_url = admin_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
        eng = _sa.create_engine(sync_admin_url)
        with eng.begin() as conn:
            conn.exec_driver_sql(
                "ALTER FUNCTION auth_user_by_email(text) OWNER TO postgres"
            )
            conn.exec_driver_sql(
                "GRANT ALL ON FUNCTION auth_user_by_email(text) TO outreach"
            )
        eng.dispose()

    with ThreadPoolExecutor(max_workers=1) as _ex_fix:
        _ex_fix.submit(_fix_auth_function).result()

    yield  # type: ignore[misc]


@pytest_asyncio.fixture(autouse=True)
async def _truncate() -> None:
    """Truncate domain tables after each test. RLS does not apply to
    TRUNCATE, so this works even when no app.current_tenant is set."""
    yield
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE tenant, app_user, credential, mailbox, audit_event, "
                "icp, lead_source, lead, scraping_job, proxy, "
                "campaign, campaign_step, knowledge_base_item, knowledge_base_chunk, "
                "draft, agent_run, "
                "sequence_run, sequence_step, send, reply, tracking_event, suppression, "
                "meeting, crm_connection, crm_sync_event, "
                "notification, notification_preference, slack_webhook, "
                "subscription, usage_event, billing_portal_token "
                "RESTART IDENTITY CASCADE"
            )
        )
    reset_local_workspace_cache()


@pytest_asyncio.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keys are now read from the environment / `.env`, so the developer's own
    shell (which may export a real OPENAI_API_KEY etc.) must never leak into
    the suite. Clear every provider/scraping env var the catalogue knows
    about, and point `.env` lookup at an empty temp file so a real `.env` on
    disk can't leak in either. Individual tests still `monkeypatch.setenv`
    the specific var they want to exercise."""
    for p in PROVIDERS:
        monkeypatch.delenv(env_keys.provider_key_var(p.provider), raising=False)
        monkeypatch.delenv(env_keys.provider_base_var(p.provider), raising=False)
    for kind in NON_LLM_KINDS:
        monkeypatch.delenv(env_keys.scraping_key_var(kind), raising=False)
    monkeypatch.setattr(env_keys, "_dotenv_path", lambda: tmp_path / ".env")
    env_keys.reset_env_cache()
    yield
    env_keys.reset_env_cache()


@pytest.fixture(autouse=True)
def _stub_mailer_override() -> None:
    """Install a StubMailer override before every test, reset after.

    Campaign sends now resolve their mailer via `get_mailer_override()` with
    no platform fallback (see `SendService`), so a test that exercises a send
    path without installing its own mailer needs one in place or the send
    would try to decrypt/contact a real SMTP mailbox. Tests that want to
    prove the `mailer_for_mailbox` fallback itself call
    `set_mailer_client(None)` to remove this override first.
    """
    set_mailer_client(StubMailer())
    yield
    set_mailer_client(None)


@pytest_asyncio.fixture
async def scoped_session():
    """A session bound to the local workspace's tenant via RLS, for tests that
    call service functions directly instead of going through the HTTP client."""
    await ensure_local_workspace()
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
        yield session


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose() -> None:
    yield  # type: ignore[misc]
    await dispose_engine()
    reset_for_tests()


# --- helpers ----------------------------------------------------------


def bearer(token: str) -> dict[str, str]:
    return {"X-Test-Auth": token}


async def signup(
    client: httpx.AsyncClient,
    *,
    email: str,
    password: str,
    tenant_name: str,
    tenant_slug: str | None = None,
) -> dict:
    """Create an extra tenant + owner directly in the DB (there is no signup route).

    `password` is accepted for call-site compatibility and ignored. The
    tenant.created / user.signed_up audit events the old signup route wrote
    are kept, because audit-chain tests rely on a tenant having audit rows.
    """
    tenant_id = _uuid.uuid4()
    user_id = _uuid.uuid4()
    slug = tenant_slug or f"t-{tenant_id.hex[:10]}"
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(
            text("INSERT INTO tenant (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": tenant_id, "slug": slug, "name": tenant_name},
        )
        await set_tenant_for_session(session, str(tenant_id))
        await session.execute(
            text(
                "INSERT INTO app_user (id, tenant_id, email, password_hash, role) "
                "VALUES (:id, :tid, :email, '!', 'owner')"
            ),
            {"id": user_id, "tid": tenant_id, "email": email},
        )
        await write_audit_event(
            session,
            action="tenant.created",
            target_type="tenant",
            target_id=tenant_id,
            actor_kind="system",
            payload={"name": tenant_name, "slug": slug},
        )
        await write_audit_event(
            session,
            action="user.signed_up",
            target_type="user",
            target_id=user_id,
            actor_kind="user",
            actor_id=user_id,
            payload={"tenant_slug": slug},
        )
    token = f"{tenant_id}:{user_id}:owner"
    return {
        "access_token": token,
        "refresh_token": token,
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
    }


def make_email(local: str, domain: str = "example.com") -> str:
    """Build a real email at runtime to avoid IDE/sanitiser rewriting."""
    return f"{local}@{domain}"


def unique_email(domain: str = "example.com") -> str:
    """Build a unique email per call (good for test isolation)."""
    return f"u-{_uuid.uuid4().hex[:8]}@{domain}"
