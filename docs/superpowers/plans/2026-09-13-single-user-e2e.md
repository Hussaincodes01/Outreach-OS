# Single-User End-to-End Outreach OS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Outreach OS build and run end to end with one Docker Compose command, as a single-user tool with no login, provider keys read from `.env`, SaaS-only features removed, and real SMTP sending plus IMAP reply capture.

**Architecture:** The API keeps its tenant-scoped data layer (PostgreSQL RLS) but every request is bound to one fixed local workspace instead of a JWT. Provider keys resolve from environment/.env before any stored credential. Sequence sends go out through each mailbox's own SMTP settings on a Celery beat schedule, and a second beat task polls IMAP for replies. The Next.js app drops its auth layer and SaaS pages.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL 16 + pgvector, Redis, Celery, MinIO, LiteLLM; Next.js 14, TanStack Query; Docker Compose; GreenMail (test SMTP/IMAP server).

**Spec:** `docs/superpowers/specs/2026-09-13-single-user-e2e-design.md` — read it; it is the binding authority.

## Global Constraints

- Repo root: `D:\OutreachOS\Outreach-OS` (Git Bash path `/d/OutreachOS/Outreach-OS`). Branch `single-user-e2e`. Never commit to `main`.
- Every commit message ends with a blank line then `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Never commit `.env`, `.env.production`, `apps/web/.env.local`, or any real secret.
- API quality gates (run from `apps/api`): `ruff check .` clean, `mypy src` clean (strict), `pytest` passing. Web gates (repo root): `npm run lint:web`, `npm run typecheck:web`, `npm run build:web` passing.
- Local dev infra host ports: Postgres **5433**, Redis **6380**, MinIO **9000/9001**, GreenMail SMTP **3025** / IMAP **3143**. Ports 5432 and 6379 belong to another project on this machine and must not be used.
- Local workspace identifiers (exact): `LOCAL_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")`, `LOCAL_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")`, tenant slug `local`, tenant name `My Workspace`, user email `owner@example.com`, role `owner`.
- LLM key env var: `<PROVIDER>_API_KEY`, base URL env var: `<PROVIDER>_API_BASE`, where `<PROVIDER>` = `ProviderSpec.provider` upper-cased with every non-alphanumeric char replaced by `_`. Scraping key env var: `<KIND>_API_KEY` for kinds `serper`, `proxycurl`, `rapidapi`, `scrapingbee`. Empty string = unset. Env beats stored credential rows.
- Missing LLM key must still produce HTTP `428` (`SetupRequiredError`); never fabricate model output.
- RLS stays enforced: runtime services connect as the non-superuser `outreach` role; scoped sessions call `set_tenant_for_session`.
- No new third-party runtime dependencies except `python-dotenv` (already transitive via pydantic-settings; declare it explicitly). IMAP and email parsing use the stdlib (`imaplib`, `email`).
- Do not drop database tables or edit existing Alembic migrations.

---

## File Structure (decisions locked here)

API (`apps/api/src/outreach_os/`):
- `services/local_workspace.py` (new) — fixed workspace ids + idempotent bootstrap.
- `api/deps.py` (modify) — `get_current_user` returns the local workspace context; no JWT.
- `core/env_keys.py` (new) — read a secret from environment or `.env`; env var naming helpers.
- `services/mailbox/transport.py` (new) — build a `MailerClient` from a mailbox's SMTP config.
- `services/mailbox/inbox.py` (new) — IMAP fetch + RFC 822 → `ReplyIngestIn` parsing + per-mailbox poll.
- `workers/tasks/inbox.py` (new) — Celery task `outreach_os.workers.poll_inboxes`.
- Deleted: `api/v1/auth.py`, `api/v1/users.py`, `api/v1/admin.py`, `api/v1/billing.py`, `core/auth.py`, `core/billing_client.py`, `services/billing_service.py`, `services/social_auth.py`, `services/social_login_service.py`, `services/account_email.py`, `services/mailbox/gmail_oauth.py`, `services/mailbox/graph_oauth.py`, and their schemas/tests (exact lists in tasks).

Web (`apps/web/src/`):
- Deleted: `app/(auth)/**`, `lib/auth.tsx`, `components/auth/social-buttons.tsx`, `components/account/verify-email-banner.tsx`, `app/(app)/admin/page.tsx`, `app/(app)/billing/page.tsx`.
- `app/page.tsx` → redirect to `/dashboard`.

Infra:
- `docker-compose.yml` (new, repo root) — the one-command stack.
- `scripts/init-env.mjs` (new) — create/complete `.env`.
- `scripts/e2e_smoke.py` (new) — live-stack smoke test (stdlib only).
- `infra/docker/docker-compose.dev.yml` (modify) — ports + GreenMail.
- Deleted: `infra/docker/docker-compose.prod.yml`, `.env.production.example`.

---

### Task 1: Fix the API build and stand up the local test harness

**Files:**
- Create: `apps/api/README.md`
- Modify: `apps/api/pyproject.toml` (line 9 `readme`; `[build-system]`)
- Modify: `infra/docker/Dockerfile.api` (the `COPY README.md` line)
- Modify: `infra/docker/docker-compose.dev.yml`
- Modify: `apps/api/tests/conftest.py` (env defaults at top)
- Modify: `.env.example`, `apps/api/src/outreach_os/core/config.py` (default URLs only)

**Interfaces:**
- Consumes: nothing.
- Produces: a working `apps/api/.venv` (native Windows) or documented container fallback; dev infra reachable at Postgres `localhost:5433` (superuser `postgres/postgres`, app role `outreach/outreach`, DBs `outreach` and `outreach_test`), Redis `localhost:6380`, MinIO `localhost:9000`, GreenMail SMTP `localhost:3025` / IMAP `localhost:3143`. Test command every later task uses: `cd apps/api && .venv/Scripts/python -m pytest -q`.

Root cause (verified): `pip install ./apps/api` fails in Docker and natively with `ValueError: Readme path must be within the project directory: ../../README.md` from hatchling metadata validation.

- [ ] **Step 1: Reproduce the failure**

Run: `cd /d/OutreachOS/Outreach-OS/apps/api && .venv/Scripts/python -m pip install -e ".[dev]"` (create the venv first with `py -3.11 -m venv .venv` if absent).
Expected: FAIL with `Readme path must be within the project directory`.

- [ ] **Step 2: Fix the readme path**

Create `apps/api/README.md`:

```markdown
# outreach-os-api

FastAPI backend, Celery workers and Alembic migrations for Outreach OS.
See the repository root `README.md` for setup and usage.
```

In `apps/api/pyproject.toml` change `readme = "../../README.md"` to `readme = "README.md"`, and pin the build backend so a future hatchling release cannot break the build silently: `requires = ["hatchling>=1.25,<2"]`.

In `infra/docker/Dockerfile.api` delete the line `COPY README.md ./README.md` and its now-wrong comment block above it (the package no longer reads the root README). Keep `COPY apps/api ./apps/api`.

- [ ] **Step 3: Verify install succeeds**

Run: `cd /d/OutreachOS/Outreach-OS/apps/api && .venv/Scripts/python -m pip install -e ".[dev]"`
Expected: `Successfully installed ...`. If a dependency (not the readme) fails to install natively on Windows, record the exact error in the report and use the container fallback in Step 6 for all test runs; say so in the report so later tasks are told.

- [ ] **Step 4: Move dev infra off the conflicting ports and add GreenMail**

In `infra/docker/docker-compose.dev.yml`:
- postgres `ports: ["5433:5432"]`
- redis `ports: ["6380:6379"]`
- replace the `mailhog` service with:

```yaml
  greenmail:
    image: greenmail/standalone:2.1.2
    container_name: outreach-greenmail
    restart: unless-stopped
    environment:
      # Accept any login; mailboxes are created on first delivery. Test-only server.
      GREENMAIL_OPTS: "-Dgreenmail.setup.test.smtp -Dgreenmail.setup.test.imap -Dgreenmail.auth.disabled -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.verbose"
    ports:
      - "3025:3025"
      - "3143:3143"
```

Update defaults that point at the old ports: `apps/api/tests/conftest.py` (`localhost:5432` → `localhost:5433`, `localhost:6379` → `localhost:6380`, in every `setdefault`), `apps/api/src/outreach_os/core/config.py` field defaults for `database_url`, `database_url_sync`, `redis_url`, `celery_broker_url`, `celery_result_backend`, and every URL in `.env.example`. Do **not** edit `.github/workflows/ci.yml` (CI sets its own env explicitly).

- [ ] **Step 5: Start infra and run the baseline suite**

```bash
cd /d/OutreachOS/Outreach-OS
docker compose -f infra/docker/docker-compose.dev.yml up -d postgres redis minio minio-init greenmail
docker compose -f infra/docker/docker-compose.dev.yml ps
cd apps/api && .venv/Scripts/python -m pytest -q
```

Expected: infra healthy; suite result recorded verbatim in the report (count passed/failed/skipped, and the names of any failing tests with one-line causes). Pre-existing failures are reported, not fixed, unless caused by Steps 2–4.

Also run `.venv/Scripts/python -m ruff check .` and `.venv/Scripts/python -m mypy src` and record results.

- [ ] **Step 6: Container fallback (only if Step 3 could not install natively)**

Add to `infra/docker/docker-compose.dev.yml` a `api-test` service under `profiles: ["test"]` that builds `infra/docker/Dockerfile.api` target `builder`-based image with `.[dev]` installed, mounts `../../apps/api:/app`, uses `network_mode: host` is NOT available on Docker Desktop — instead join the compose network and set `DATABASE_URL=postgresql+asyncpg://outreach:outreach@postgres:5432/outreach_test`, `DATABASE_URL_ADMIN=postgresql+asyncpg://postgres:postgres@postgres:5432/outreach_test`, `REDIS_URL=redis://redis:6379/15`, `CELERY_BROKER_URL=redis://redis:6379/15`, `CELERY_RESULT_BACKEND=redis://redis:6379/15`, `S3_ENDPOINT_URL=http://minio:9000`, command `pytest -q`. Document the command `docker compose -f infra/docker/docker-compose.dev.yml --profile test run --rm api-test` in the report. Skip this step entirely when Step 3 succeeded.

- [ ] **Step 7: Verify the production image builds**

Run: `cd /d/OutreachOS/Outreach-OS && docker build -f infra/docker/Dockerfile.api -t outreach-os-api:task1 .`
Expected: build succeeds (the `pip install ./apps/api[prod]` layer passes).

- [ ] **Step 8: Commit**

```bash
git add apps/api/README.md apps/api/pyproject.toml infra/docker/Dockerfile.api infra/docker/docker-compose.dev.yml apps/api/tests/conftest.py apps/api/src/outreach_os/core/config.py .env.example
git commit -m "Fix the API build and move dev infra off conflicting ports

Hatchling rejects a readme outside the project directory, so pip install
of apps/api failed in Docker and natively.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Remove authentication — every request uses the local workspace

**Files:**
- Create: `apps/api/src/outreach_os/services/local_workspace.py`
- Create: `apps/api/tests/test_local_workspace.py`
- Modify: `apps/api/src/outreach_os/api/deps.py`
- Modify: `apps/api/src/outreach_os/main.py` (router list, lifespan, CORS `allow_headers`)
- Modify: `apps/api/src/outreach_os/api/v1/notifications.py` (WebSocket auth)
- Modify: `apps/api/src/outreach_os/core/config.py` (remove `jwt_*`, `password_reset_ttl_minutes`, `email_verification_ttl_hours`, `google_login_redirect_uri`, `microsoft_login_redirect_uri`, `auth_rate_limits_per_minute` keys `login`/`signup`/`refresh`/`password_reset` usage; remove the JWT check in `_enforce_production_safety`)
- Modify: `apps/api/src/outreach_os/services/user_service.py` (drop password hashing)
- Modify: `apps/api/tests/conftest.py` (test-only auth override; `signup`/`bearer` helpers)
- Delete: `api/v1/auth.py`, `core/auth.py`, `services/social_auth.py`, `services/social_login_service.py`, `services/account_email.py`, `domain/schemas/auth.py` members only used by auth routes (keep `AuthContext`), `tests/test_auth.py`, `tests/test_account_recovery.py`, `tests/test_social_login.py`
- Test: `apps/api/tests/test_local_workspace.py`, existing suite

**Interfaces:**
- Consumes: Task 1 harness.
- Produces:
  - `outreach_os.services.local_workspace.LOCAL_TENANT_ID: uuid.UUID`, `LOCAL_USER_ID: uuid.UUID`, `LOCAL_TENANT_SLUG = "local"`, `LOCAL_TENANT_NAME = "My Workspace"`, `LOCAL_USER_EMAIL = "owner@example.com"`
  - `async def ensure_local_workspace() -> None` (idempotent, opens its own session)
  - `def reset_local_workspace_cache() -> None` (tests call after truncation)
  - `def local_auth_context() -> AuthContext` → `AuthContext(user_id=LOCAL_USER_ID, tenant_id=LOCAL_TENANT_ID, role="owner")`
  - `outreach_os.api.deps.get_current_user() -> AuthContext` (async, no parameters)
  - `get_scoped_db`, `get_db` unchanged signatures; `require_platform_admin` and `get_admin_db` still exist until Task 3 deletes them (Task 3 owns admin removal).
  - Test helpers in `tests/conftest.py`: `bearer(token: str) -> dict[str, str]` returning `{"X-Test-Auth": token}`; `async def signup(client, *, email, password, tenant_name, tenant_slug=None) -> dict` returning keys `access_token`, `refresh_token`, `user_id`, `tenant_id` (tokens are the string `"<tenant_id>:<user_id>:owner"`).
  - `core/mailer.py`, `services/mailbox/gmail_oauth.py`, `graph_oauth.py` are NOT touched here (Task 5 owns them). If either OAuth module imports `core.auth`, keep the minimal function it needs by moving it into that module rather than deleting OAuth code.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_local_workspace.py`:

```python
"""The API runs as one built-in workspace: no Authorization header needed."""
from __future__ import annotations

import uuid

import httpx
from sqlalchemy import text

from outreach_os.core.db import get_engine
from outreach_os.services.local_workspace import (
    LOCAL_TENANT_ID,
    LOCAL_USER_ID,
    ensure_local_workspace,
    reset_local_workspace_cache,
)


async def test_tenant_me_works_without_authorization(client: httpx.AsyncClient) -> None:
    resp = await client.get("/v1/tenants/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(LOCAL_TENANT_ID)
    assert body["slug"] == "local"
    assert body["name"] == "My Workspace"


async def test_ensure_local_workspace_is_idempotent() -> None:
    reset_local_workspace_cache()
    await ensure_local_workspace()
    reset_local_workspace_cache()
    await ensure_local_workspace()
    async with get_engine().connect() as conn:
        tenants = (
            await conn.execute(text("SELECT count(*) FROM tenant WHERE id = :id"), {"id": LOCAL_TENANT_ID})
        ).scalar_one()
    assert tenants == 1


async def test_writes_are_scoped_to_local_workspace(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/v1/icps",
        json={"name": "Local ICP", "description": "d", "target_titles": ["CTO"]},
    )
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["tenant_id"] == str(LOCAL_TENANT_ID)


async def test_auth_routes_are_gone(client: httpx.AsyncClient) -> None:
    assert (await client.post("/v1/auth/login", json={})).status_code == 404
    assert (await client.post("/v1/auth/signup", json={})).status_code == 404


def test_local_ids_are_fixed() -> None:
    assert LOCAL_TENANT_ID == uuid.UUID("00000000-0000-4000-8000-000000000001")
    assert LOCAL_USER_ID == uuid.UUID("00000000-0000-4000-8000-000000000002")
```

If `ICPCreate` requires different fields or `ICPOut` has no `tenant_id`, read `domain/schemas` for the ICP schema and adjust the payload/assertion to the real field names while keeping the assertion's intent (the created row belongs to `LOCAL_TENANT_ID`; verify via SQL as the superuser if the response omits it).

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_local_workspace.py -q`
Expected: FAIL — `ModuleNotFoundError: outreach_os.services.local_workspace`.

- [ ] **Step 3: Implement the local workspace**

`apps/api/src/outreach_os/services/local_workspace.py`:

```python
"""The single built-in workspace every request runs as.

Outreach OS runs as a single-user tool: there is no signup or login. The data
layer is still tenant-scoped (PostgreSQL RLS), so one fixed tenant and owner
user are created on first use and every request binds to them.
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import text

from outreach_os.core.db import get_session_factory
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.schemas.auth import AuthContext

LOCAL_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
LOCAL_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
LOCAL_TENANT_SLUG = "local"
LOCAL_TENANT_NAME = "My Workspace"
LOCAL_USER_EMAIL = "owner@example.com"

_ensured = False
_lock = asyncio.Lock()


def local_auth_context() -> AuthContext:
    return AuthContext(user_id=LOCAL_USER_ID, tenant_id=LOCAL_TENANT_ID, role="owner")


def reset_local_workspace_cache() -> None:
    """Forget that the rows exist. Tests call this after truncating tables."""
    global _ensured
    _ensured = False


async def ensure_local_workspace() -> None:
    """Create the local tenant and owner user if missing. Safe to call repeatedly."""
    global _ensured
    if _ensured:
        return
    async with _lock:
        if _ensured:
            return
        factory = get_session_factory()
        async with factory() as session, session.begin():
            # tenant is not RLS-protected; app_user is, so bind the GUC first.
            await session.execute(
                text(
                    "INSERT INTO tenant (id, slug, name) VALUES (:id, :slug, :name) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": LOCAL_TENANT_ID, "slug": LOCAL_TENANT_SLUG, "name": LOCAL_TENANT_NAME},
            )
            await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
            await session.execute(
                text(
                    "INSERT INTO app_user (id, tenant_id, email, password_hash, role) "
                    "VALUES (:id, :tid, :email, '!', 'owner') ON CONFLICT (id) DO NOTHING"
                ),
                {"id": LOCAL_USER_ID, "tid": LOCAL_TENANT_ID, "email": LOCAL_USER_EMAIL},
            )
        _ensured = True
```

Check the real table names in `domain/models/tenant.py` and `domain/models/user.py` (`__tablename__`) and any other NOT NULL columns without server defaults; adjust the SQL to match. `password_hash='!'` is a deliberately unusable value — nothing verifies passwords any more.

- [ ] **Step 4: Replace JWT dependencies**

In `api/deps.py`: delete `_bearer_token`, the `jose`/`core.auth` imports, and rewrite:

```python
async def get_current_user() -> AuthContext:
    """The single local workspace. There is no authentication."""
    await ensure_local_workspace()
    return local_auth_context()
```

Update the module docstring to describe the single-workspace model. Keep `get_db` and `get_scoped_db` as they are.

In `api/v1/notifications.py`: the WebSocket endpoint no longer takes `token`; it binds to `LOCAL_TENANT_ID` after `await ensure_local_workspace()`. Remove the `core.auth` import and the token docstring.

In `main.py`: remove `auth` (and `users`) from the import list and `app.include_router` calls; delete `api/v1/users.py`; call `await ensure_local_workspace()` in `lifespan` after logging "starting" (wrap in try/except that logs `local_workspace_bootstrap_failed` and continues, so `/health` still answers when the DB is down); change CORS `allow_headers` to `["Content-Type"]`.

In `services/user_service.py`: remove `hash_password` usage; if `create_user` is now unused anywhere (`grep -rn create_user src tests`), delete it.

Delete the files listed under **Files → Delete**. Then `grep -rn "core.auth\|social_login\|account_email\|decode_token\|create_access_token" src` must return nothing except inside `services/mailbox/gmail_oauth.py`/`graph_oauth.py` (handled per Interfaces note). Remove now-unused settings from `core/config.py` as listed, and the JWT problem from `_enforce_production_safety`. Remove `rate_limit` callers for `login`, `signup`, `refresh`, `password_reset` (the webhook limit stays).

- [ ] **Step 5: Test-only auth override in conftest**

Tests keep testing cross-tenant RLS isolation, so they need to act as different tenants. Production has no such mechanism; tests install a dependency override:

```python
# tests/conftest.py — replace bearer() and signup()
import uuid as _uuid

from outreach_os.api.deps import get_current_user
from outreach_os.domain.schemas.auth import AuthContext
from outreach_os.services.local_workspace import local_auth_context, reset_local_workspace_cache


async def _test_current_user(x_test_auth: str | None = Header(default=None)) -> AuthContext:
    """Test-only: act as the tenant encoded in X-Test-Auth, else the local workspace."""
    if not x_test_auth:
        from outreach_os.services.local_workspace import ensure_local_workspace

        await ensure_local_workspace()
        return local_auth_context()
    tenant_id, user_id, role = x_test_auth.split(":")
    return AuthContext(user_id=_uuid.UUID(user_id), tenant_id=_uuid.UUID(tenant_id), role=role)


app.dependency_overrides[get_current_user] = _test_current_user


def bearer(token: str) -> dict[str, str]:
    return {"X-Test-Auth": token}


async def signup(client, *, email: str, password: str, tenant_name: str, tenant_slug: str | None = None) -> dict:
    """Create an extra tenant + owner directly in the DB (there is no signup route)."""
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
    token = f"{tenant_id}:{user_id}:owner"
    return {"access_token": token, "refresh_token": token, "user_id": str(user_id), "tenant_id": str(tenant_id)}
```

(Use the real table names found in Step 3; import `Header` from fastapi, `get_session_factory`, `set_tenant_for_session`.) In the `_truncate` autouse fixture call `reset_local_workspace_cache()` after truncating. Remove the auth rate-limit env default keys that no longer exist (keep `webhook`). Tests that asserted a `401` for a missing/invalid token must be deleted or changed to assert the new behaviour (request succeeds as local workspace); tests that exercised WebSocket `?token=` must connect without a token.

- [ ] **Step 6: Run tests**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q` then `ruff check .` and `mypy src`.
Expected: `test_local_workspace.py` passes; the full suite passes except tests that belong to Task 3 scope (`test_phase7_billing.py`, `test_admin_console.py`) — if those fail only because auth helpers changed, fix them minimally or leave them failing and list them in the report as "Task 3 deletes". ruff and mypy clean.

- [ ] **Step 7: Commit**

```bash
git add -A apps/api
git commit -m "Remove authentication: every request runs as one local workspace

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Remove billing, plans, the admin console and team users

**Files:**
- Delete: `api/v1/billing.py`, `api/v1/admin.py`, `core/billing_client.py`, `services/billing_service.py`, `domain/schemas/admin.py`, `domain/schemas/phase7.py` (only if nothing else imports it — check with grep; otherwise remove just the billing schemas), `tests/test_phase7_billing.py`, `tests/test_admin_console.py`, `scripts/seed_admin.py`
- Modify: `main.py` (routers), `api/deps.py` (delete `require_platform_admin`, `get_admin_db`), `api/v1/leads.py:115-145` (limit check + usage recording), `api/v1/crm.py` (`BillingError` import/handling), `services/crm_service.py:180-200,270-290` (plan gating), `services/send_service.py:238-252` (usage recording), `workers/tasks/scrape.py:135-150` (usage recording), `tests/conftest.py` (`_seed_plans` fixture), `api/v1/tenants.py` (drop `plan` from PATCH if writable), `services/onboarding_service.py` (any plan/billing step)
- Test: existing suite; `tests/test_saas_removed.py` (new)

**Interfaces:**
- Consumes: Task 2 (`get_current_user`, conftest helpers).
- Produces: no billing symbols anywhere in `src`. `TenantOut` may still include `plan` (column still exists) — leave the schema field; the web ignores it.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/test_saas_removed.py`:

```python
"""Single-user build: no billing, plans, admin console, or team users."""
from __future__ import annotations

import pathlib

import httpx
import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "outreach_os"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/billing/plans"),
        ("get", "/v1/billing/subscription"),
        ("get", "/v1/admin/customers"),
        ("get", "/v1/admin/stats"),
        ("get", "/v1/users"),
    ],
)
async def test_saas_routes_are_gone(client: httpx.AsyncClient, method: str, path: str) -> None:
    resp = await getattr(client, method)(path)
    assert resp.status_code in (404, 405), f"{path} -> {resp.status_code}"


def test_no_billing_code_left() -> None:
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if "billing_service" in p.read_text(encoding="utf-8")
        or "require_platform_admin" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


async def test_lead_create_has_no_plan_cap(client: httpx.AsyncClient) -> None:
    # Far beyond any old plan's monthly lead cap would be slow; one create proves
    # the path no longer consults billing (it used to 402/429 without a plan row).
    resp = await client.post(
        "/v1/leads",
        json={"email": "cap-test@example.org", "first_name": "Cap", "company_name": "Acme"},
    )
    assert resp.status_code in (200, 201), resp.text
```

Adjust the billing/admin paths to the real ones in `api/v1/billing.py` / `admin.py` (read their `@router` decorators and `prefix`) and the lead-create payload to `LeadCreate`'s real required fields before deleting those files.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_saas_removed.py -q`
Expected: FAIL (routes return 200/401-type codes, grep finds `billing_service`).

- [ ] **Step 3: Remove the code**

Delete the files listed. At each call site: remove the `check_within_limits` try/except in `leads.py` entirely (no cap), delete `record_usage` blocks in `send_service.py` and `scrape.py`, delete plan gating in `crm_service.py` (CRM calls proceed), remove `BillingError` handling in `crm.py`. Remove `_seed_plans` from conftest. Remove the billing beat/rollup settings (`billing_provider`, `stripe_*`, `billing_rollup_interval_seconds`) from `core/config.py` and the stripe checks in `_enforce_production_safety`. Remove `require_platform_admin` / `get_admin_db` from `deps.py` and `__all__`. `grep -rni "billing\|stripe\|platform_admin" src` should only hit model/migration-adjacent names you intentionally keep (models of existing tables); remove the model imports from `domain/models/__init__.py` only if nothing references them and Alembic autogenerate is not used by tests (check `alembic/env.py` — if it imports all models for metadata, keep the model files).

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest -q`, `ruff check .`, `mypy src`.
Expected: all pass, clean.

- [ ] **Step 5: Commit**

```bash
git add -A apps/api scripts
git commit -m "Remove billing, plans, the admin console and team users

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Read provider API keys from `.env`

**Files:**
- Create: `apps/api/src/outreach_os/core/env_keys.py`
- Create: `apps/api/tests/test_env_keys.py`
- Modify: `apps/api/pyproject.toml` (add `"python-dotenv>=1.0,<2.0"`)
- Modify: `apps/api/src/outreach_os/services/llm_credentials.py` (`load_credentials`, provider catalogue data)
- Modify: `apps/api/src/outreach_os/services/credential_lookup.py` (`get_credential_secrets`)
- Modify: `apps/api/src/outreach_os/api/v1/credentials.py` (providers listing, new test + scraping endpoints)
- Modify: `apps/api/src/outreach_os/domain/schemas/credential.py` (new fields/schemas)
- Modify: `apps/api/src/outreach_os/services/onboarding_service.py` (llm_key / llm_verified steps)
- Modify: `.env.example` (provider key section)

**Interfaces:**
- Consumes: Task 2 local workspace; `ProviderSpec`, `PROVIDERS`, `NON_LLM_KINDS`, `LLMCredentials`, `verify_credentials`/`_achat_probe` in `llm_credentials.py`.
- Produces:
  - `core/env_keys.py`: `def env_value(name: str) -> str | None`; `def provider_key_var(provider: str) -> str`; `def provider_base_var(provider: str) -> str`; `def scraping_key_var(kind: str) -> str`; `def reset_env_cache() -> None`
  - `llm_credentials.env_credentials(provider: str) -> LLMCredentials | None`
  - `ProviderOut` gains `env_var: str`, `env_base_var: str`, `configured_via: Literal["env", "stored"] | None`
  - `POST /v1/credentials/providers/{provider}/test` → `ProviderTestOut {ok: bool, message: str}`; on success stores `tenant.onboarding_state["verified_providers"][provider] = <UTC ISO timestamp>`; `ProviderOut.last_verified_at` reads it for env-configured providers.
  - `GET /v1/credentials/scraping` → `list[ScrapingKeyOut {kind: str, env_var: str, configured: bool}]`

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_env_keys.py`:

```python
"""Provider keys come from environment / .env, ahead of stored credentials."""
from __future__ import annotations

import uuid

import httpx
import pytest

from outreach_os.core import env_keys
from outreach_os.core.llm import set_llm_client  # adjust import to where the test override lives
from outreach_os.services import credential_lookup, llm_credentials
from outreach_os.services.local_workspace import LOCAL_TENANT_ID


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    # Point .env lookup at an empty file so the developer's real .env never leaks in.
    monkeypatch.setattr(env_keys, "_dotenv_path", lambda: tmp_path / ".env")
    for var in ("OPENAI_API_KEY", "SERPER_API_KEY", "OLLAMA_API_BASE"):
        monkeypatch.delenv(var, raising=False)
    env_keys.reset_env_cache()


def test_var_names() -> None:
    assert env_keys.provider_key_var("openai") == "OPENAI_API_KEY"
    assert env_keys.provider_key_var("together-ai") == "TOGETHER_AI_API_KEY"
    assert env_keys.provider_base_var("ollama") == "OLLAMA_API_BASE"
    assert env_keys.scraping_key_var("serper") == "SERPER_API_KEY"


def test_env_value_reads_process_env_then_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    (tmp_path / ".env").write_text("SERPER_API_KEY=from-dotenv\nOPENAI_API_KEY=\n", encoding="utf-8")
    env_keys.reset_env_cache()
    assert env_keys.env_value("SERPER_API_KEY") == "from-dotenv"
    assert env_keys.env_value("OPENAI_API_KEY") is None  # empty counts as unset
    monkeypatch.setenv("SERPER_API_KEY", "from-process")
    assert env_keys.env_value("SERPER_API_KEY") == "from-process"


def test_env_credentials_for_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    creds = llm_credentials.env_credentials("openai")
    assert creds is not None
    assert creds.api_key == "sk-env"


async def test_resolve_prefers_env(monkeypatch: pytest.MonkeyPatch, scoped_session) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    set_llm_client(None)
    client = await llm_credentials.resolve_llm_client(
        scoped_session, tenant_id=LOCAL_TENANT_ID, model="openai/gpt-4o-mini"
    )
    assert isinstance(client, llm_credentials.LiteLLMClient)
    assert client.credentials.api_key == "sk-env"  # adjust attribute name to LiteLLMClient's


async def test_missing_key_is_428(client: httpx.AsyncClient) -> None:
    set_llm_client(None)
    resp = await client.get("/v1/credentials/providers")
    assert resp.status_code == 200
    openai = next(p for p in resp.json() if p["provider"] == "openai")
    assert openai["connected"] is False
    assert openai["env_var"] == "OPENAI_API_KEY"


async def test_provider_listing_reports_env(monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    resp = await client.get("/v1/credentials/providers")
    openai = next(p for p in resp.json() if p["provider"] == "openai")
    assert openai["connected"] is True
    assert openai["configured_via"] == "env"


async def test_scraping_keys_from_env(monkeypatch: pytest.MonkeyPatch, scoped_session, client: httpx.AsyncClient) -> None:
    monkeypatch.setenv("SERPER_API_KEY", "serp-env")
    got = await credential_lookup.get_credential_secrets(
        scoped_session, tenant_id=LOCAL_TENANT_ID, kinds=["serper", "proxycurl"]
    )
    assert got == {"serper": "serp-env"}
    listing = (await client.get("/v1/credentials/scraping")).json()
    assert {"kind": "serper", "env_var": "SERPER_API_KEY", "configured": True} in listing
```

Before writing: find the real names — the test LLM override setter (grep `def set_llm_client\|def get_llm_client`), the `LiteLLMClient` attribute holding credentials, whether `/v1/credentials/providers` returns a list or `{items: [...]}`, and whether a `scoped_session` fixture exists (if not, add one to conftest: a session bound via `set_tenant_for_session` to `LOCAL_TENANT_ID` after `ensure_local_workspace()`). Also add a test for the missing-key path through drafting if an existing test covers `428` — keep that test passing unchanged.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_env_keys.py -q`
Expected: FAIL — `ImportError: cannot import name 'env_keys'`.

- [ ] **Step 3: Implement `core/env_keys.py`**

```python
"""Provider API keys supplied by the operator through environment / .env.

This is a single-user build: one workspace, one operator, so keys configured
for the process belong to that operator. Values come from the process
environment first (Docker `env_file`), then from the `.env` file Settings reads
(native runs, where .env is not exported into os.environ).
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")


def _dotenv_path() -> Path:
    return Path(".env")


@lru_cache(maxsize=1)
def _dotenv() -> dict[str, str | None]:
    path = _dotenv_path()
    return dict(dotenv_values(path)) if path.is_file() else {}


def reset_env_cache() -> None:
    _dotenv.cache_clear()


def env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        value = _dotenv().get(name)
    value = (value or "").strip()
    return value or None


def _prefix(name: str) -> str:
    return _NON_ALNUM.sub("_", name).upper()


def provider_key_var(provider: str) -> str:
    return f"{_prefix(provider)}_API_KEY"


def provider_base_var(provider: str) -> str:
    return f"{_prefix(provider)}_API_BASE"


def scraping_key_var(kind: str) -> str:
    return f"{_prefix(kind)}_API_KEY"
```

Add `"python-dotenv>=1.0,<2.0",` to `[project].dependencies` and reinstall (`pip install -e ".[dev]"`).

- [ ] **Step 4: Wire resolution**

In `llm_credentials.py` add:

```python
def env_credentials(provider: str) -> LLMCredentials | None:
    """Credentials for `provider` from environment / .env, or None if unset."""
    spec = _BY_PROVIDER.get(provider)
    if spec is None:
        raise UnknownProviderError(f"unsupported provider {provider!r}")
    api_key = env_value(provider_key_var(provider)) or ""
    api_base = env_value(provider_base_var(provider)) or ""
    if spec.requires_api_base and not api_base:
        return None
    if spec.requires_api_key and not api_key:
        return None
    if not spec.requires_api_key and not api_key:
        if not api_base:
            return None  # a keyless provider (Ollama) is configured by its base URL
        api_key = "not-required"
    return LLMCredentials(provider=spec.provider, api_key=api_key, api_base=api_base or spec.api_base_hint)
```

and at the top of `load_credentials` (after the spec lookup): `env = env_credentials(provider); if env is not None: return env`. In `credential_lookup.get_credential_secrets`: compute `out` from stored rows as today, then overlay `{kind: v for kind in kinds if (v := env_value(scraping_key_var(kind)))}` so env wins.

In `api/v1/credentials.py` providers listing: set `connected=True`, `configured_via="env"` when `env_credentials(provider)` is not None; else existing stored-row logic with `configured_via="stored"` when connected, `None` otherwise; always fill `env_var`/`env_base_var`; `last_verified_at` from `tenant.onboarding_state.get("verified_providers", {}).get(provider)` for env providers. Add the `POST /credentials/providers/{provider}/test` endpoint: 404 for unknown provider, `428` (raise `MissingLLMCredentialsError`) when neither env nor stored creds exist, else probe with the same function the existing credential Test endpoint uses (reuse it — do not duplicate the probe) and on success record the timestamp in `onboarding_state` (reassign the dict so SQLAlchemy sees the change) and write an audit event `credential.provider.verified`. Add `GET /credentials/scraping` iterating `NON_LLM_KINDS`.

In `onboarding_service.py`: `llm_key` step done if any provider has `env_credentials` or a stored row; `llm_verified` done if `onboarding_state["verified_providers"]` is non-empty or a stored row has `last_verified_at`; step `href` stays `/integrations`; the step description tells the user to set the key in `.env` and restart.

In `.env.example` add a commented block listing every provider's key var (generate the list from `PROVIDERS` so names are exact — e.g. run `python -c "from outreach_os.services.llm_credentials import PROVIDERS; from outreach_os.core.env_keys import *; [print(provider_key_var(p.provider)) for p in PROVIDERS]"`) plus `SERPER_API_KEY`, `PROXYCURL_API_KEY`, `RAPIDAPI_API_KEY`, `SCRAPINGBEE_API_KEY`, all empty.

Remove the "never read from the process environment" invariant comments/docstrings in `llm_credentials.py` and `credential_lookup.py` and replace with one sentence on precedence (env first). Existing BYOK tests asserting the environment is ignored (`grep -rn "environ" tests/test_byok_credentials.py`) must be updated to assert the new precedence instead.

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python -m pytest -q`, `ruff check .`, `mypy src`.
Expected: all pass, clean.

- [ ] **Step 6: Commit**

```bash
git add -A apps/api .env.example
git commit -m "Read provider API keys from .env ahead of stored credentials

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Send sequence emails through the mailbox's own SMTP, on schedule

**Files:**
- Create: `apps/api/src/outreach_os/services/mailbox/transport.py`
- Create: `apps/api/tests/test_mailbox_transport.py`
- Modify: `apps/api/src/outreach_os/core/mailer.py` (add `get_mailer_override`)
- Modify: `apps/api/src/outreach_os/services/send_service.py:46-50` and the mailer call in `execute_step`
- Modify: `apps/api/src/outreach_os/services/mailbox/mailer.py` (`_send_smtp` reuses transport; remove gmail/outlook branches)
- Modify: `apps/api/src/outreach_os/workers/celery_app.py` (beat schedule)
- Modify: `apps/api/src/outreach_os/api/v1/mailboxes.py` (delete `/oauth/gmail/*`, `/oauth/outlook/*` routes)
- Modify: `apps/api/src/outreach_os/core/config.py` (remove `google_oauth_*`, `microsoft_oauth_*`)
- Modify: `apps/api/tests/conftest.py` (autouse StubMailer override)
- Modify: `apps/api/pyproject.toml` (drop `python-jose`, `passlib`, `bcrypt`, `types-passlib` if nothing imports them)
- Delete: `services/mailbox/gmail_oauth.py`, `services/mailbox/graph_oauth.py`, tests that only cover Gmail/Outlook OAuth mailbox connection

**Interfaces:**
- Consumes: Task 2/3/4 state; `Mailbox` model (`provider`, `email_address`, `smtp_config_ciphertext`, `tenant_id`); `vault_service.decrypt_for_tenant(tenant_id: str, ciphertext: bytes) -> dict`; `SmtpMailer(*, host, port, username, password, use_tls, default_from, timeout=10)`; `set_mailer_client(client | None)`.
- Produces:
  - `core.mailer.get_mailer_override() -> MailerClient | None` — the client installed via `set_mailer_client`, or None.
  - `services.mailbox.transport.smtp_config(mailbox: Mailbox) -> dict[str, Any]` (decrypted; raises `MailError` if missing/undecryptable)
  - `services.mailbox.transport.mailer_for_mailbox(mailbox: Mailbox) -> MailerClient`
  - Beat entry `"outreach_os.workers.send_due"` every `settings.send_due_interval_seconds`.
  - The encrypted SMTP config dict keys stay `host`, `port`, `username`, `password`, `use_tls` (Task 6 adds IMAP keys to the same dict).

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_mailbox_transport.py`:

```python
"""Sequence sends use the sending mailbox's SMTP settings, and run on schedule."""
from __future__ import annotations

import uuid

from outreach_os.core.mailer import SmtpMailer, get_mailer_override, set_mailer_client
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.services import vault_service
from outreach_os.services.local_workspace import LOCAL_TENANT_ID
from outreach_os.services.mailbox.transport import mailer_for_mailbox
from outreach_os.workers.celery_app import celery_app


def _smtp_mailbox() -> Mailbox:
    cfg = {"host": "smtp.example.org", "port": 587, "username": "me", "password": "pw", "use_tls": True}
    return Mailbox(
        id=uuid.uuid4(),
        tenant_id=LOCAL_TENANT_ID,
        provider="smtp",
        email_address="me@example.org",
        smtp_config_ciphertext=vault_service.encrypt_for_tenant(str(LOCAL_TENANT_ID), cfg),
    )


def test_mailer_for_smtp_mailbox_uses_its_settings() -> None:
    mailer = mailer_for_mailbox(_smtp_mailbox())
    assert isinstance(mailer, SmtpMailer)
    assert mailer._host == "smtp.example.org"
    assert mailer._port == 587
    assert mailer._username == "me"
    assert mailer._default_from == "me@example.org"


def test_override_is_none_until_set() -> None:
    set_mailer_client(None)
    assert get_mailer_override() is None


def test_send_due_is_on_beat_schedule() -> None:
    tasks = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    assert "outreach_os.workers.send_due" in tasks


async def test_gmail_oauth_routes_are_gone(client) -> None:
    assert (await client.get("/v1/mailboxes/oauth/gmail/start")).status_code == 404
    assert (await client.get("/v1/mailboxes/oauth/outlook/start")).status_code == 404
```

Also add to `tests/test_phase4_send.py` (or wherever a sequence send is executed end-to-end with a StubMailer) a test that, with NO override installed, `SendService(session)` picks `mailer_for_mailbox(mailbox)`: monkeypatch `outreach_os.services.send_service.mailer_for_mailbox` to return a recording stub and assert it received the message with `from_email == mailbox.email_address`. Note: the autouse conftest fixture in Step 3 installs a StubMailer override; this test must call `set_mailer_client(None)` first. Check `vault_service` function names and adjust.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_mailbox_transport.py -q`
Expected: FAIL — `ModuleNotFoundError: outreach_os.services.mailbox.transport`.

- [ ] **Step 3: Implement**

`core/mailer.py`: keep a separate module global `_override: MailerClient | None`; `set_mailer_client` sets it (and keeps existing behaviour for `get_mailer_client`); add `def get_mailer_override() -> MailerClient | None: return _override`. Read the file first and keep `get_transactional_mailer` intact.

`services/mailbox/transport.py`:

```python
"""Outbound transport for a connected mailbox.

Campaign mail must leave through the user's own mailbox — never a shared
platform server — so recipients see a real sender and replies land in an inbox
the user controls.
"""
from __future__ import annotations

from typing import Any

from outreach_os.core.errors import MailError
from outreach_os.core.mailer import MailerClient, SmtpMailer
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.services import vault_service


def smtp_config(mailbox: Mailbox) -> dict[str, Any]:
    if mailbox.provider != "smtp" or not mailbox.smtp_config_ciphertext:
        raise MailError(f"mailbox {mailbox.email_address} has no SMTP configuration")
    try:
        cfg = vault_service.decrypt_for_tenant(str(mailbox.tenant_id), mailbox.smtp_config_ciphertext)
    except Exception as exc:
        raise MailError(f"mailbox {mailbox.email_address}: SMTP settings cannot be decrypted") from exc
    return dict(cfg)


def mailer_for_mailbox(mailbox: Mailbox) -> MailerClient:
    cfg = smtp_config(mailbox)
    return SmtpMailer(
        host=str(cfg["host"]),
        port=int(cfg["port"]),
        username=str(cfg.get("username") or "") or None,
        password=str(cfg.get("password") or "") or None,
        use_tls=bool(cfg.get("use_tls", True)),
        default_from=mailbox.email_address,
    )
```

`SendService.__init__`: `self._mailer = mailer or get_mailer_override()` (no platform fallback). In `execute_step`, before step 8, resolve `mailer = self._mailer or mailer_for_mailbox(mailbox)` inside the existing `try` so a `MailError`/`MailerError` marks the send failed through the existing failure branch (extend the `except` to `(MailerError, MailError)`). Replace uses of `self.mailer` accordingly.

`services/mailbox/mailer.py`: `_send_smtp` builds its client with `mailer_for_mailbox(mailbox)` and sends an `OutgoingMessage` (keep the audit write and return shape); delete the gmail/outlook branches so non-smtp providers raise `MailError("unsupported provider")`.

`workers/celery_app.py` `beat_schedule`: add

```python
        "outreach_os.workers.send_due": {
            "task": "outreach_os.workers.send_due",
            "schedule": float(settings.send_due_interval_seconds),
        },
```

Delete the OAuth mailbox routes and modules, the OAuth settings, and any schema only they used (`OAuthStartResponse` if unused). Conftest: add an autouse fixture that `set_mailer_client(StubMailer())` before each test and `set_mailer_client(None)` after. Then check `grep -rn "jose\|passlib\|bcrypt" src tests` — if empty, remove those dependencies from `pyproject.toml` and reinstall.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest -q`, `ruff check .`, `mypy src`.
Expected: all pass, clean.

- [ ] **Step 5: Commit**

```bash
git add -A apps/api
git commit -m "Send sequence mail through the mailbox's own SMTP on a beat schedule

Sends previously went through the platform mailer, a stub unless SMTP_HOST
was set, and send_due was never scheduled. Gmail/Outlook OAuth mailboxes
only pretended to send and are removed; SMTP covers both via app passwords.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Capture replies by polling the mailbox over IMAP

**Files:**
- Create: `apps/api/src/outreach_os/services/mailbox/inbox.py`
- Create: `apps/api/src/outreach_os/workers/tasks/inbox.py`
- Create: `apps/api/tests/test_inbox_polling.py`
- Modify: `apps/api/src/outreach_os/domain/schemas/mailbox.py` (`SmtpCreate`, `MailboxOut`)
- Modify: `apps/api/src/outreach_os/api/v1/mailboxes.py` (`POST /smtp` stores IMAP keys; `MailboxOut.imap_enabled`)
- Modify: `apps/api/src/outreach_os/workers/tasks/__init__.py`, `workers/celery_app.py`, `core/config.py` (`inbox_poll_interval_seconds: int = 120`, `inbox_poll_lookback_days: int = 14`)

**Interfaces:**
- Consumes: Task 5 `smtp_config(mailbox)`; `ReplyService(session, llm=...)`, `ReplyService.ingest(*, tenant_id, data: ReplyIngestIn) -> Reply | None`; `ReplyIngestIn(message_id_header, from_email, from_name, subject, body_text, body_html, received_at, in_reply_to, references)`; `set_tenant_for_session`; `LOCAL_TENANT_ID`.
- Produces:
  - `SmtpCreate` new optional fields: `imap_host: str | None = None`, `imap_port: int = Field(default=993, ge=1, le=65535)`, `imap_use_ssl: bool = True`. Stored in the SMTP config dict under keys `imap_host`, `imap_port`, `imap_use_ssl` (IMAP login reuses `username`/`password`).
  - `MailboxOut.imap_enabled: bool`
  - `inbox.parse_message(raw: bytes) -> ReplyIngestIn | None`
  - `inbox.FetchFn = Callable[[dict[str, Any]], list[bytes]]`; `inbox.fetch_unseen(cfg: dict[str, Any]) -> list[bytes]`
  - `async def inbox.poll_mailbox(session: AsyncSession, mailbox: Mailbox, *, fetch: FetchFn = fetch_unseen) -> int` (returns replies ingested)
  - `workers.tasks.inbox.poll_inboxes_async(*, fetch: FetchFn | None = None) -> dict[str, int]`; Celery task name `outreach_os.workers.poll_inboxes`, beat every `settings.inbox_poll_interval_seconds`.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/test_inbox_polling.py`:

```python
"""IMAP replies are matched to the original send and ingested."""
from __future__ import annotations

from email.message import EmailMessage

from outreach_os.services.mailbox.inbox import parse_message
from outreach_os.workers.celery_app import celery_app


def _raw_reply(in_reply_to: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = "Pat Prospect <pat@prospect.example>"
    msg["To"] = "me@example.org"
    msg["Subject"] = "Re: Quick question"
    msg["Message-ID"] = "<reply-1@prospect.example>"
    msg["In-Reply-To"] = in_reply_to
    msg["References"] = in_reply_to
    msg["Date"] = "Sun, 13 Sep 2026 10:00:00 +0000"
    msg.set_content("Sounds good, let's talk Tuesday.")
    msg.add_alternative("<p>Sounds good, let's talk Tuesday.</p>", subtype="html")
    return msg.as_bytes()


def test_parse_message_extracts_threading_headers() -> None:
    data = parse_message(_raw_reply("<send-abc@outreach>"))
    assert data is not None
    assert data.from_email == "pat@prospect.example"
    assert data.from_name == "Pat Prospect"
    assert data.message_id_header == "<reply-1@prospect.example>"
    assert data.in_reply_to == "<send-abc@outreach>"
    assert "Tuesday" in data.body_text
    assert data.body_html is not None and "<p>" in data.body_html


def test_parse_message_without_message_id_is_skipped() -> None:
    msg = EmailMessage()
    msg["From"] = "x@y.example"
    msg.set_content("hi")
    assert parse_message(msg.as_bytes()) is None


def test_poll_inboxes_on_beat_schedule() -> None:
    tasks = {e["task"] for e in celery_app.conf.beat_schedule.values()}
    assert "outreach_os.workers.poll_inboxes" in tasks


async def test_poll_ingests_reply_for_real_send(client, sent_send) -> None:
    """`sent_send` fixture: an SMTP mailbox (with imap_host) plus a Send row in
    status 'sent' for the local workspace, created through the existing phase-4
    test helpers. Returns (mailbox_id, message_id_header)."""
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    _mailbox_id, message_id = sent_send
    summary = await poll_inboxes_async(fetch=lambda cfg: [_raw_reply(message_id)])
    assert summary["ingested"] == 1
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    assert any(r["from_email"] == "pat@prospect.example" for r in items)
```

Build the `sent_send` fixture in this file by reusing how `tests/test_phase4_send.py` creates mailbox → lead → campaign/sequence → executed send with the StubMailer (read that file; call the same helpers). Create the mailbox via `POST /v1/mailboxes/smtp` with `imap_host="imap.example.org"`. The reply classifier needs an LLM: use the same fake LLM injection `test_phase4_reply.py` uses.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_inbox_polling.py -q`
Expected: FAIL — `ModuleNotFoundError: outreach_os.services.mailbox.inbox`.

- [ ] **Step 3: Implement `services/mailbox/inbox.py`**

```python
"""Read replies from a mailbox over IMAP and hand them to the reply engine."""
from __future__ import annotations

import imaplib
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.config import get_settings
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.domain.schemas.phase4 import ReplyIngestIn
from outreach_os.services.mailbox.transport import smtp_config
from outreach_os.services.reply_service import ReplyService

log = logging.getLogger(__name__)

FetchFn = Callable[[dict[str, Any]], list[bytes]]


def parse_message(raw: bytes) -> ReplyIngestIn | None:
    msg = message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        return None
    from_name, from_email = parseaddr(str(msg.get("From") or ""))
    text_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    body_text = text_part.get_content().strip() if text_part is not None else ""
    body_html = html_part.get_content() if html_part is not None else None
    if not body_text:
        body_text = "(no text body)"
    received_at = None
    if msg.get("Date"):
        try:
            received_at = parsedate_to_datetime(str(msg["Date"])).astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            received_at = None
    return ReplyIngestIn(
        message_id_header=message_id,
        from_email=from_email.lower(),
        from_name=from_name or None,
        subject=str(msg.get("Subject") or "") or None,
        body_text=body_text,
        body_html=body_html,
        received_at=received_at,
        in_reply_to=(str(msg.get("In-Reply-To") or "").strip() or None),
        references=(str(msg.get("References") or "").strip() or None),
    )


def fetch_unseen(cfg: dict[str, Any]) -> list[bytes]:
    """Fetch unseen messages from INBOX received in the lookback window, marking them seen."""
    settings = get_settings()
    host = str(cfg["imap_host"])
    port = int(cfg.get("imap_port") or 993)
    client: imaplib.IMAP4 = imaplib.IMAP4_SSL(host, port) if cfg.get("imap_use_ssl", True) else imaplib.IMAP4(host, port)
    try:
        client.login(str(cfg["username"]), str(cfg["password"]))
        client.select("INBOX")
        since = (datetime.now(timezone.utc) - timedelta(days=settings.inbox_poll_lookback_days)).strftime("%d-%b-%Y")
        status, data = client.search(None, "UNSEEN", "SINCE", since)
        if status != "OK" or not data or not data[0]:
            return []
        out: list[bytes] = []
        for num in data[0].split():
            status, parts = client.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            for part in parts:
                if isinstance(part, tuple) and isinstance(part[1], bytes):
                    out.append(part[1])
            client.store(num, "+FLAGS", "\\Seen")
        return out
    finally:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


async def poll_mailbox(session: AsyncSession, mailbox: Mailbox, *, fetch: FetchFn = fetch_unseen) -> int:
    cfg = smtp_config(mailbox)
    if not cfg.get("imap_host"):
        return 0
    raws = fetch(cfg)
    service = ReplyService(session)
    ingested = 0
    for raw in raws:
        data = parse_message(raw)
        if data is None:
            continue
        if await service.ingest(tenant_id=mailbox.tenant_id, data=data) is not None:
            ingested += 1
    return ingested
```

`fetch` is blocking; `poll_mailbox` must run it via `await asyncio.to_thread(fetch, cfg)` — use that instead of the direct call above. Note `ingest` rolls back the session on a duplicate (`IntegrityError`); if that invalidates the RLS GUC for subsequent messages, re-bind with `set_tenant_for_session` after a `None` result, and cover it with a test that polls two messages where the first is a duplicate.

`workers/tasks/inbox.py`: follow the structure of `workers/tasks/send.py`/`send_tasks.py` exactly (async core + sync Celery wrapper using `asyncio.run`, same logging style). The async core opens a session with `get_session_factory()`, binds `LOCAL_TENANT_ID`, selects active mailboxes with `provider == "smtp"`, and calls `poll_mailbox` per mailbox inside its own `try` (log and continue on `MailError`, `imaplib.IMAP4.error`, `OSError`), committing after each mailbox. Returns `{"mailboxes": n, "ingested": total, "errors": e}`. Register the module in `workers/tasks/__init__.py`, add the beat entry, add the settings.

Mailboxes API: extend `SmtpCreate`, store the three IMAP keys in the encrypted dict only when `imap_host` is given, and set `imap_enabled` on `MailboxOut` (decrypt config in the listing; a decrypt failure → `False`).

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest -q`, `ruff check .`, `mypy src`.
Expected: all pass, clean.

- [ ] **Step 5: Commit**

```bash
git add -A apps/api
git commit -m "Capture replies by polling SMTP mailboxes over IMAP

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Web — remove auth, billing, admin and the landing page

**Files:**
- Delete: `apps/web/src/app/(auth)/` (whole directory), `apps/web/src/lib/auth.tsx`, `apps/web/src/components/auth/social-buttons.tsx`, `apps/web/src/components/account/verify-email-banner.tsx`, `apps/web/src/app/(app)/admin/page.tsx`, `apps/web/src/app/(app)/billing/page.tsx`
- Modify: `apps/web/src/app/page.tsx`, `apps/web/src/components/providers.tsx`, `apps/web/src/app/(app)/layout.tsx`, `apps/web/src/components/nav/sidebar.tsx`, `apps/web/src/lib/api-client.ts`, `apps/web/src/app/(app)/notifications/page.tsx`, `apps/web/src/app/(app)/settings/page.tsx`, `apps/web/src/app/(app)/dashboard/page.tsx`, `apps/web/src/components/onboarding/setup-checklist.tsx`, `apps/web/src/components/leads/import-dialog.tsx` (only where they reference removed APIs/auth/billing)

**Interfaces:**
- Consumes: API after Tasks 2–6 — no auth headers; no `/v1/auth`, `/v1/users`, `/v1/billing`, `/v1/admin`; WebSocket `/v1/notifications/ws` without `token`.
- Produces: `api` client object with no `setAccessToken`, `login`, `signup`, `refresh`, `me`, `forgotPassword`, `resetPassword`, `verifyEmail`, billing or admin methods; no `useApiAuthBridge`; no `useAuth` anywhere. Task 8 edits `integrations/page.tsx` and `mailboxes/page.tsx` (leave those two pages functionally as they are here, only removing auth/billing references if the build requires it).

- [ ] **Step 1: Capture the failing check**

Run from repo root:
```bash
grep -rln "useAuth\|setAccessToken\|/login\|/signup\|billing\|/admin\|Authorization" apps/web/src
```
Expected: lists the files above (this grep is the acceptance check; it must return nothing except `mailboxes/page.tsx` and `integrations/page.tsx` references Task 8 owns, and no match for `Authorization`/`useAuth` at all).

- [ ] **Step 2: Root redirect**

`apps/web/src/app/page.tsx`:

```tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/dashboard");
}
```

- [ ] **Step 3: Strip auth from providers, layout, sidebar, client**

`providers.tsx`: remove `AuthProvider` import and wrapper (keep QueryClientProvider).
`(app)/layout.tsx`: remove `VerifyEmailBanner`.
`sidebar.tsx`: remove `useAuth`, `useApiAuthBridge`, the login redirect effect, the user email line, the Sign out button, `AdminLink`, `ADMIN_NAV`, and the `Billing` and `CRM sync` NAV entries; remove icon imports that become unused (`LogOut`, `ShieldCheck`, `CreditCard`, `Link2`, `useRouter`, `useEffect`). `UnreadBadge` drops `enabled: !!user`. Footer shows the text `Local workspace` in the same muted style the email line used.
`api-client.ts`: remove `inMemoryToken`, the auth header helper and every place it is spread into headers, `setAccessToken`, `signup`, `login`, `refresh`, `me`, password-reset/verify/social methods, admin and billing methods and their interfaces (`TokenPair`, `SignupInput`, `Admin*`, billing types, `SocialProviderOut`), and `useApiAuthBridge` (and the `useAuth` import). Build the notifications WebSocket URL without a `token` parameter. On a `401` the client must not redirect anywhere (there is no login).
`notifications/page.tsx`, `settings/page.tsx`, `dashboard/page.tsx`, `setup-checklist.tsx`, `import-dialog.tsx`: remove auth/billing/team-user usage (e.g. settings page team members section, plan display, `accessToken` guards). Keep workspace name and model-picker settings.
Delete the files listed under Files → Delete. `app/(app)/crm/page.tsx` stays on disk but is unlinked from navigation (spec: CRM is out of scope).

- [ ] **Step 4: Verify**

```bash
cd /d/OutreachOS/Outreach-OS
grep -rn "useAuth\|setAccessToken\|Authorization\|/login\|/signup" apps/web/src   # expect no output
npm run lint:web && npm run typecheck:web && npm run build:web
```
Expected: grep empty; all three commands succeed.

- [ ] **Step 5: Commit**

```bash
git add -A apps/web
git commit -m "Web: open straight into the app with no login, billing or admin

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Web — integrations from `.env` and SMTP+IMAP mailboxes

**Files:**
- Modify: `apps/web/src/app/(app)/integrations/page.tsx`
- Modify: `apps/web/src/app/(app)/mailboxes/page.tsx`
- Modify: `apps/web/src/lib/api-client.ts` (types + methods below)

**Interfaces:**
- Consumes (API, Tasks 4–6):
  - `GET /v1/credentials/providers` → providers with `provider, label, console_url, description, connected, configured_via ("env"|"stored"|null), env_var, env_base_var, requires_api_key, requires_api_base, last_verified_at, supports_embeddings` (check the exact wrapper shape — list vs `{items}` — against the Task 4 implementation in `api/v1/credentials.py`).
  - `POST /v1/credentials/providers/{provider}/test` → `{ok: boolean, message: string}`; `428` when not configured.
  - `GET /v1/credentials/scraping` → `{kind, env_var, configured}[]`.
  - `POST /v1/mailboxes/smtp` body `{email_address, host, port, username, password, use_tls, daily_send_cap, imap_host?, imap_port?, imap_use_ssl?}`; `MailboxOut.imap_enabled: boolean`.
- Produces: `api.testProvider(provider: string): Promise<{ ok: boolean; message: string }>`, `api.scrapingKeys(): Promise<ScrapingKeyOut[]>`; `ProviderOut` gains `configured_via`, `env_var`, `env_base_var`; `MailboxOut` gains `imap_enabled`; `SmtpMailboxInput` gains the three IMAP fields.

- [ ] **Step 1: Integrations page**

Replace the key-entry form with a read-only status list. For each provider card: label + description; badge `Configured` (when `connected`) or `Not configured`; the line `Set <code>{env_var}</code>` (and `{env_base_var}` when `requires_api_base`) `in .env, then restart the stack.`; a link to `console_url` ("Get a key"); a `Test` button (enabled only when `connected`) that calls `api.testProvider` and shows `toast.success(message)` / `toast.error(message)` (sonner is already used in the app), then invalidates the providers query; `Verified <relative time>` when `last_verified_at`. A second section "Lead data sources" lists `api.scrapingKeys()` with the same configured/env-var line. Keep the existing model picker (`components/settings/model-picker.tsx`) wherever the page currently renders it. Remove any create/delete-credential UI and their now-unused client methods.

- [ ] **Step 2: Mailboxes page**

Remove the Gmail and Outlook connect buttons and OAuth callback handling. The SMTP form gains an "Receive replies (IMAP)" section: `IMAP host` (optional), `IMAP port` (default 993), `Use SSL` checkbox (default checked). Help text under the form: `Gmail: smtp.gmail.com:587 and imap.gmail.com:993 with an app password. Outlook: smtp.office365.com:587 and outlook.office365.com:993.` Mailbox list rows show a `Replies: IMAP` badge when `imap_enabled`, otherwise `Replies: webhook only`.

- [ ] **Step 3: Verify**

```bash
cd /d/OutreachOS/Outreach-OS
grep -rn "oauth/gmail\|oauth/outlook\|createCredential" apps/web/src   # expect no output
npm run lint:web && npm run typecheck:web && npm run build:web
```
Expected: grep empty; all succeed.

- [ ] **Step 4: Commit**

```bash
git add -A apps/web
git commit -m "Web: show .env provider status and add IMAP settings to mailboxes

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: One-command Docker Compose stack

**Files:**
- Create: `docker-compose.yml` (repo root)
- Create: `scripts/init-env.mjs`
- Modify: `package.json` (scripts), `.env.example`, `infra/docker/Dockerfile.web` (only if the build needs it), `.github/workflows/ci.yml` (remove obsolete JWT env; add `docker compose config -q` check)
- Delete: `infra/docker/docker-compose.prod.yml`, `.env.production.example` (do NOT delete the untracked `.env.production`)

**Interfaces:**
- Consumes: all API/web tasks.
- Produces: `npm run setup` (creates/completes `.env`), `npm start` = `docker compose up -d --build`, `npm stop` = `docker compose down`. Services: `postgres`, `redis`, `minio`, `migrate`, `api` (host 8000), `worker`, `beat`, `web` (host 3000), and `greenmail` (host 3025/3143) under profile `e2e`. Task 10's smoke script targets `http://localhost:8000` and GreenMail on `localhost:3025`/`3143`, with the API reaching GreenMail at host `greenmail` inside the network.

- [ ] **Step 1: Write the env initialiser**

`scripts/init-env.mjs`:

```js
// Create .env from .env.example if missing, and fill secrets that must not be blank.
// Never overwrites a value that is already set.
import { existsSync, readFileSync, writeFileSync, copyFileSync } from "node:fs";
import { randomBytes } from "node:crypto";

const ENV = ".env";
if (!existsSync(ENV)) {
  copyFileSync(".env.example", ENV);
  console.log("created .env from .env.example");
}

const generators = {
  // Fernet key: urlsafe base64 of 32 random bytes.
  VAULT_MASTER_KEY: () => randomBytes(32).toString("base64url") + "=",
  INBOUND_WEBHOOK_SECRET: () => randomBytes(32).toString("hex"),
};

let text = readFileSync(ENV, "utf8");
for (const [key, make] of Object.entries(generators)) {
  const re = new RegExp(`^${key}=(.*)$`, "m");
  const m = text.match(re);
  if (!m) {
    text += `${text.endsWith("\n") ? "" : "\n"}${key}=${make()}\n`;
    console.log(`added ${key}`);
  } else if (!m[1].trim() || m[1].trim().startsWith("replace-with")) {
    text = text.replace(re, `${key}=${make()}`);
    console.log(`generated ${key}`);
  }
}
writeFileSync(ENV, text);
console.log("Add your provider API keys to .env (see the provider section), then run: npm start");
```

Verify the Fernet key format: `base64url` of 32 bytes is 43 chars; Fernet requires 44-char urlsafe base64 with padding — confirm with `python -c "from cryptography.fernet import Fernet; Fernet(b'<generated>')"` inside the API venv and fix the generator if it fails.

- [ ] **Step 2: Write `docker-compose.yml`**

Derive it from `infra/docker/docker-compose.prod.yml` (same `migrate` superuser override, same worker/beat commands, same postgres initdb mount — paths now relative to the repo root: `./infra/docker/postgres/initdb`, build `context: .`), with these changes:
- `name: outreach-os`
- `env_file: [.env]` for app services.
- Runtime env for api/worker/beat/migrate adds `S3_ENDPOINT_URL: http://minio:9000`, `S3_ACCESS_KEY: minioadmin`, `S3_SECRET_KEY: minioadmin`, `CELERY_TASK_ALWAYS_EAGER: "false"`, `ENVIRONMENT: ${ENVIRONMENT:-development}`, `PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-http://localhost:8000}`.
- `minio` service (`minio/minio:RELEASE.2025-04-22T22-12-26Z` or the latest tag you verify pulls), `command: server /data --console-address ":9001"`, env `MINIO_ROOT_USER/PASSWORD=minioadmin`, volume `minio-data`, healthcheck `["CMD", "mc", "ready", "local"]` (verify it passes; fall back to a TCP check if `mc` is absent). api/worker/beat `depends_on` minio healthy. No host ports for postgres/redis/minio.
- `web` build arg `NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL:-http://localhost:8000}`, ports `3000:3000`.
- `greenmail` service identical to the dev compose one, plus `profiles: ["e2e"]`.

`package.json` scripts: add `"setup": "node scripts/init-env.mjs"`, `"start": "docker compose up -d --build"`, `"stop": "docker compose down"`, `"logs": "docker compose logs -f api worker beat"`. Change `"dev:infra"` to `docker compose -f infra/docker/docker-compose.dev.yml up -d postgres redis minio minio-init greenmail`.

In `core/config.py` confirm the production validator no longer mentions JWT/stripe (Tasks 2/3) and that `ENVIRONMENT=development` with `CELERY_TASK_ALWAYS_EAGER=false` boots cleanly. In `.env.example` remove `JWT_*`, `NEXTAUTH_*`, and add a header comment explaining the one-command flow.

- [ ] **Step 3: Bring it up and verify**

```bash
cd /d/OutreachOS/Outreach-OS
npm run setup
docker compose config -q
docker compose --profile e2e up -d --build
docker compose ps
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/health/ready
curl -fsS http://localhost:8000/v1/tenants/me
curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:3000/dashboard
docker compose logs migrate | tail -5
docker compose logs beat | grep -E "send_due|poll_inboxes" | head
```
Expected: all services `running`/`healthy` (`migrate` exited 0); health `{"status":"ok"}` twice; tenants/me returns slug `local`; web `200`; beat logs show both schedules firing. Paste the outputs into the report.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml scripts/init-env.mjs package.json .env.example .github/workflows/ci.yml infra/docker apps/api/src/outreach_os/core/config.py
git rm --cached -q .env.production.example 2>/dev/null; git add -A infra .env.production.example
git commit -m "Run the whole stack with one docker compose command

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

(Before committing, run `git status --short` and confirm `.env` and `.env.production` are not staged.)

---

### Task 10: End-to-end smoke test against the live stack, and docs

**Files:**
- Create: `scripts/e2e_smoke.py`
- Modify: `package.json` (`"smoke": "python scripts/e2e_smoke.py"`)
- Modify: `README.md`, `SETUP.md`, `docs/runbook.md`, `docs/architecture.md`, `docs/threat-model.md`, `OUTREACH_OS.md`

**Interfaces:**
- Consumes: the running stack from Task 9 (with `--profile e2e`); API routes as implemented in Tasks 2–6 (read the routers for exact payloads: ICPs, leads import `POST /v1/leads/import`, mailboxes `POST /v1/mailboxes/smtp` and `POST /v1/mailboxes/{id}/send-test`, campaigns, drafts, sequences, sends, replies, onboarding).
- Produces: `python scripts/e2e_smoke.py [--api http://localhost:8000] [--imap-host localhost --imap-port 3143 --smtp-host-internal greenmail]` exiting 0 when every non-skipped check passes; prints one line per check: `PASS name`, `FAIL name: reason`, or `SKIP name: reason`.

- [ ] **Step 1: Write the smoke script (stdlib only)**

Checks, in order (each a function returning a result; the script continues after a FAIL only when later checks do not depend on it):
1. `health` — `GET /health` and `/health/ready` are `ok`.
2. `workspace` — `GET /v1/tenants/me` slug `local`, with no auth header.
3. `onboarding` — `GET /v1/onboarding` (real path) returns `steps`.
4. `icp` — create an ICP.
5. `lead_import` — import a 1-row CSV (`email=prospect-<uuid>@greenmail.test`, name, company) via multipart built with `email.mime` / manual boundary; expect `imported == 1`.
6. `mailbox` — create SMTP mailbox `sender-<uuid>@greenmail.test`, host `greenmail`, port `3025`, `use_tls=false`, username/password = the address, `imap_host=greenmail`, `imap_port=3143`, `imap_use_ssl=false`.
7. `smtp_delivery` — `POST /v1/mailboxes/{id}/send-test` to the prospect address; then poll GreenMail IMAP from the host (`imaplib.IMAP4("localhost", 3143)`, login prospect address/any password) for up to 30 s until a message with the test subject exists.
8. `llm_configured` — `GET /v1/credentials/providers`; if none `connected`, SKIP checks 9–11 with reason `no LLM key in .env`.
9. `provider_test` — `POST /v1/credentials/providers/{provider}/test` for the first connected provider; `ok` true.
10. `draft_send_reply` — create campaign → generate draft for the lead → start sequence → wait (≤ 3× `SEND_DUE_INTERVAL_SECONDS`, default 60 s) for a send with status `sent` → confirm GreenMail received it and read its `Message-ID` → deliver a reply over SMTP (`smtplib.SMTP("localhost", 3025)`) from the prospect to the sender with `In-Reply-To` set → wait ≤ 3× `INBOX_POLL_INTERVAL_SECONDS` (default 120 s) for `GET /v1/replies` to contain it. If the send window blocks sending, the check must say so explicitly (read `SEND_WINDOW_*` from the API behaviour/logs) rather than time out silently; set `SEND_WINDOW_START_HOUR=0` and `SEND_WINDOW_END_HOUR=24` in `.env` for the run if needed and note it in the report.
11. `ws_notifications` — optional: skip.

Run it against the stack: `docker compose --profile e2e up -d --build && python scripts/e2e_smoke.py`. Paste the full output in the report. Checks 1–7 must PASS. Checks 8–10 PASS if a key is configured in `.env`, otherwise SKIP.

- [ ] **Step 2: Update the docs**

- `README.md`: replace Quick Start with: clone → `npm run setup` → add keys to `.env` → `npm start` → open `http://localhost:3000`. Replace the "Bring Your Own Key" section with "API keys in `.env`" (env var naming rule; which keys each feature needs: an LLM key for drafting/replies, `SERPER_API_KEY` for web search scraping, `PROXYCURL_API_KEY` for LinkedIn enrichment). Remove billing/pricing/multi-tenant-SaaS/login claims from the module table, "Why this project stands out", Architecture table (Auth row), and Roadmap entries that are now done (lead import). Describe mailboxes: SMTP + IMAP, Gmail/Outlook app passwords. Add `npm run smoke`. Remove the Windows litellm warning if Task 1 proved native install works (keep it otherwise).
- `SETUP.md`: env var table without JWT/NEXTAUTH; provider key section (env naming rule, precedence); dev infra ports 5433/6380/9000/3025/3143; test commands.
- `docs/runbook.md`: one-command deploy via root `docker-compose.yml`; required env now `VAULT_MASTER_KEY` (+ production-only checks that remain); verification commands from Task 9 Step 3; failure modes updated (428 → add key to `.env` and restart; IMAP login failures → app password; send window); keep the RLS/roles/backups sections; state that the stack has no login and must not be exposed to the internet without a reverse proxy with its own authentication.
- `docs/architecture.md`: tenancy section rewritten for the single local workspace (RLS still bound per request); add sending/reply-polling flow.
- `docs/threat-model.md`: replace JWT/auth threats with "no authentication: bind to localhost or put behind an authenticating proxy"; env-key handling.
- `OUTREACH_OS.md`: capabilities/status aligned with the above; known gaps = CRM and calendar clients are stubs.

- [ ] **Step 3: Verify**

```bash
cd /d/OutreachOS/Outreach-OS
python scripts/e2e_smoke.py
grep -rniE "sign ?up|log ?in|JWT|billing|stripe|pricing" README.md SETUP.md docs OUTREACH_OS.md
```
Expected: smoke exit 0 with checks 1–7 PASS; the grep shows only intentional mentions (e.g. "no login", "Gmail app password" sign-in context) — list any remaining hits in the report with a reason.

- [ ] **Step 4: Commit**

```bash
git add scripts/e2e_smoke.py package.json README.md SETUP.md docs OUTREACH_OS.md
git commit -m "Add a live-stack smoke test and document the single-user setup

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
