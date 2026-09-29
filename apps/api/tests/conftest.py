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
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production-use-please")
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/15")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6380/15")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6380/15")
# Run Celery tasks synchronously in-process so tests don't need a worker.
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
# Every test shares one client IP, so production limits would make the suite
# fail on volume rather than behaviour. `password_reset` is included because it
# defaults to a deliberately tight 3/min.
os.environ.setdefault(
    "AUTH_RATE_LIMITS_PER_MINUTE",
    '{"login": 10000, "signup": 10000, "refresh": 10000, "webhook": 10000,'
    ' "password_reset": 10000}',
)
# Set inbound webhook secret for tests
os.environ.setdefault("INBOUND_WEBHOOK_SECRET", "test-webhook-secret")
# The httpx test client uses base_url="http://test" (Host `test`), and
# Starlette's TestClient (the WebSocket tests) sends Host `testserver`.
# TrustedHostMiddleware reads this at app import, below.
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1,test,testserver")

import uuid as _uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from outreach_os.core import env_keys
from outreach_os.core.db import dispose_engine, get_engine, get_session_factory, reset_for_tests
from outreach_os.core.mailer import StubMailer, set_mailer_client
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.main import app
from outreach_os.services.llm_credentials import NON_LLM_KINDS, PROVIDERS


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
async def account(client: httpx.AsyncClient) -> dict:
    """A freshly signed-up workspace (tenant + owner) with real tokens.

    Tests that need "the" workspace use this; tests proving isolation call
    `signup()` again for a second one.
    """
    return await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Test Workspace",
    )


@pytest_asyncio.fixture
async def account_tenant_id(account: dict) -> _uuid.UUID:
    return _uuid.UUID(account["tenant_id"])


@pytest_asyncio.fixture
async def authed_client(client: httpx.AsyncClient, account: dict) -> httpx.AsyncClient:
    """The shared test client, signed in as `account` on every request."""
    client.headers.update(bearer(account["access_token"]))
    return client


@pytest_asyncio.fixture
async def scoped_session(account: dict):
    """A session bound to `account`'s tenant via RLS, for tests that call
    service functions directly instead of going through the HTTP client."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, account["tenant_id"])
        yield session


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose() -> None:
    yield  # type: ignore[misc]
    await dispose_engine()
    reset_for_tests()


# --- helpers ----------------------------------------------------------


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def signup(
    client: httpx.AsyncClient,
    *,
    email: str,
    password: str,
    tenant_name: str,
    tenant_slug: str | None = None,
) -> dict:
    body: dict[str, str] = {
        "email": email,
        "password": password,
        "tenant_name": tenant_name,
    }
    if tenant_slug:
        body["tenant_slug"] = tenant_slug
    resp = await client.post("/v1/auth/signup", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_email(local: str, domain: str = "example.com") -> str:
    """Build a real email at runtime to avoid IDE/sanitiser rewriting."""
    return f"{local}@{domain}"


def unique_email(domain: str = "example.com") -> str:
    """Build a unique email per call (good for test isolation)."""
    return f"u-{_uuid.uuid4().hex[:8]}@{domain}"
