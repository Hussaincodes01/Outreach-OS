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
    "postgresql+asyncpg://outreach:outreach@localhost:5432/outreach_test",
)
os.environ.setdefault(
    "TEST_DATABASE_URL",
    os.environ["DATABASE_URL"],
)
# Migrations need the bootstrap superuser. The app itself still uses DATABASE_URL
# above (the non-superuser) so RLS is enforced under test.
os.environ.setdefault(
    "DATABASE_URL_ADMIN",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/outreach_test",
)
os.environ.setdefault("VAULT_MASTER_KEY", "2QU3n0T0Q3n0T0Q3n0T0Q3n0T0Q3n0T0Q3n0T0Q3n0Q=")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production-use-please")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/15")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/15")
# Run Celery tasks synchronously in-process so tests don't need a worker.
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
# Disable auth rate limits in tests (or set very high)
os.environ.setdefault("AUTH_RATE_LIMITS_PER_MINUTE", '{"login": 10000, "signup": 10000, "refresh": 10000, "webhook": 10000}')
# Set inbound webhook secret for tests
os.environ.setdefault("INBOUND_WEBHOOK_SECRET", "test-webhook-secret")

import httpx
import pytest_asyncio
from sqlalchemy import text

from outreach_os.core.db import dispose_engine, get_engine, reset_for_tests
from outreach_os.main import app


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

    # 4) Seed plan rows (the migration seeds them against the *default*
    #    DB, but tests run against outreach_test. Idempotent INSERT.)
    #    Also drop RLS on billing_portal_token — its token IS the capability.
    def _seed_plans() -> None:
        import sqlalchemy as _sa
        from sqlalchemy import text as _t

        # Admin connection: DROP POLICY / ALTER TABLE require table ownership,
        # and migrations now run as the superuser (see step 2), so the tables
        # are owned by the admin role rather than the app role.
        admin_url = os.environ.get("DATABASE_URL_ADMIN", os.environ["DATABASE_URL"])
        url = admin_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
        eng = _sa.create_engine(url)
        with eng.begin() as conn:
            conn.execute(_t(
                """
                INSERT INTO plan (code, name, monthly_price_cents, monthly_send_cap,
                                  monthly_lead_cap, monthly_llm_token_cap,
                                  crm_sync_enabled, slack_notifications_enabled,
                                  email_digest_enabled, max_team_seats, max_mailboxes,
                                  display_order)
                VALUES
                  ('starter',  'Starter',  2900,  500,    1000, 200000, false, false, false, 1, 1, 1),
                  ('growth',   'Growth',   9900,  5000,   25000, 1500000, true,  true,  true,  5, 10, 2),
                  ('scale',    'Scale',    29900, 25000,  100000, 10000000, true, true,  true,  25, 50, 3)
                ON CONFLICT (code) DO NOTHING
                """
            ))
            # billing_portal_token is a capability, not a tenant resource.
            conn.exec_driver_sql(
                "DROP POLICY IF EXISTS tenant_isolation_billing_portal_token ON billing_portal_token"
            )
            conn.exec_driver_sql(
                "ALTER TABLE billing_portal_token DISABLE ROW LEVEL SECURITY"
            )
            conn.exec_driver_sql(
                "ALTER TABLE billing_portal_token NO FORCE ROW LEVEL SECURITY"
            )
        eng.dispose()

    with ThreadPoolExecutor(max_workers=1) as _ex2:
        _ex2.submit(_seed_plans).result()

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
    import uuid as _uuid

    return f"u-{_uuid.uuid4().hex[:8]}@{domain}"
