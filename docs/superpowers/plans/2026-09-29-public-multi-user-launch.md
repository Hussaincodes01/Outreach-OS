# Public Multi-User Launch — Phase 1 (Code) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-workspace build into a public, multi-user, horizontally scalable app (accounts, private workspaces, bring-your-own keys, usage limits, compliant sending) that is ready to deploy to Vercel + Render.

**Architecture:** Restore the original account system from git history (baseline commit `0147bed`) on top of today's code, keeping every fix made since. Background work fans out per mailbox / per workspace across two Celery queues. Sending becomes idempotent and compliant. Deployment config for Render (API, workers, beat, managed Postgres/Redis) and Vercel (web) lives in the repo. Phase 2 (provisioning) and Phase 3 (launch) are a separate plan written once the owner's accounts exist.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL 16 + pgvector + RLS, Redis, Celery 5, LiteLLM, boto3 (S3/R2), Next.js 14, TanStack Query, Docker, Render Blueprint, Vercel, Sentry.

**Spec:** `docs/superpowers/specs/2026-09-29-public-multi-user-launch-design.md` — the binding authority. Read it.

## Global Constraints

- Repo root `D:\OutreachOS\Outreach-OS` (Git Bash `/d/OutreachOS/Outreach-OS`). Branch `public-multi-user` (based on `groq-models-env-settings` at `fdf2b21`). Never commit to `main`.
- Every commit message ends with a blank line then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never commit `.env`, `.env.production`, `apps/web/.env.local`, or any real secret. Never print secret values.
- API gates (from `apps/api`): `.venv/Scripts/python -m ruff check .`, `.venv/Scripts/python -m mypy src` (strict), full pytest passing. pytest's summary line is swallowed in this shell: always pass `-p no:cacheprovider --junitxml=<file>` and read tests/failures/errors/skipped from the XML. Never run two pytest processes at once. Run the full suite in foreground chunks if it would exceed 10 minutes.
- Web gates (repo root): `npm run lint:web`, `npm run typecheck:web`, `npm run build:web`.
- Dev infra (tests): `docker compose -f infra/docker/docker-compose.dev.yml up -d postgres redis rustfs` → Postgres `localhost:5433`, Redis `6380`, RustFS (S3) `9000`. Ports 5432/6379 belong to another project (`wa_postgres`, `wa_redis`) — never touch them.
- RLS stays enforced; runtime connects as the non-superuser `outreach` role; scoped sessions call `set_tenant_for_session`.
- Existing Alembic migrations are never edited; new migrations are allowed (next number `0019`).
- Restoring code from history: use `git show 0147bed:<path>` (and the other commits named per task). Restore, then adapt to today's code — never overwrite a file wholesale without re-applying fixes made since (listed per task).
- Sign-in methods: email+password and Google only (no Microsoft).
- Public endpoints that stay unauthenticated: tracking pixel, click, unsubscribe (GET + POST), inbound reply webhook, `/health`, `/health/ready`, Google OAuth start/callback, auth signup/login/refresh/forgot/reset/verify.
- Provider keys come only from each workspace's encrypted credentials. Env/.env provider keys only when `ALLOW_ENV_PROVIDER_KEYS=true` (default `false`); production startup fails if `true`.
- Usage limit defaults (settings): `LIMIT_SENDS_PER_DAY=200`, `DEFAULT_DAILY_SEND_CAP=50`, `LIMIT_LEADS_PER_MONTH=1000`, `LIMIT_CONCURRENT_SCRAPES=2`, `LIMIT_MAILBOXES=3`, `LIMIT_DRAFTS_PER_HOUR=100`. Warm-up: start 10/day, +10/day.
- New third-party dependencies allowed only where a task names them: `pip-tools` (dev), `@sentry/nextjs` (web).

---

## File Structure (decisions locked here)

API (`apps/api/src/outreach_os/`):
- Restored: `core/auth.py`, `api/v1/auth.py`, `api/v1/users.py` (me/password/delete only), `api/v1/admin.py`, `services/user_service.py`, `services/account_email.py`, `services/social_auth.py`, `services/social_login_service.py`, `domain/schemas/auth.py` members, `domain/schemas/admin.py`.
- Removed: `services/local_workspace.py` and every `LOCAL_TENANT_ID` use.
- New: `core/signing.py` (signed link tokens), `services/usage_limits.py` (limits + usage recording), `services/mailbox/warmup.py` (effective daily cap), `services/mailbox/bounces.py` (hard-bounce detection), `workers/tasks/fanout.py` (beat dispatchers), migration `alembic/versions/0019_public_launch.py`.
- Modified: `api/deps.py`, `main.py`, `core/config.py`, `core/mailer.py`, `services/send_service.py`, `services/mailbox/inbox.py`, `workers/celery_app.py`, `workers/tasks/{inbox,send,send_tasks,scrape}.py`, `services/llm_credentials.py`, `services/credential_lookup.py`, `api/v1/{credentials,onboarding,tracking,gdpr,leads,mailboxes,scraping_jobs,drafts,notifications}.py`.

Web (`apps/web/src/`):
- Restored (from `d0dd2cd^`): `app/(auth)/**` minus Microsoft, `lib/auth.tsx`, `components/auth/social-buttons.tsx` (Google only), `components/account/verify-email-banner.tsx`, `app/(app)/admin/page.tsx`.
- Restored (from `36c4c22^`): key-entry UI on `app/(app)/integrations/page.tsx`.
- New: `app/(legal)/terms/page.tsx`, `app/(legal)/acceptable-use/page.tsx`, settings sections (password, delete account, postal address, usage).

Deploy:
- New: `render.yaml`, `apps/api/requirements.lock`, `docs/deploy.md`.
- Modified: `infra/docker/Dockerfile.api`, `infra/docker/Dockerfile.web`, `docker-compose.yml`, `.env.example`, `scripts/init-env.mjs`, `scripts/e2e_smoke.py`, `.github/workflows/ci.yml`.

---

### Task 1: Reproducible, fast builds and a green CI

**Files:**
- Create: `apps/api/requirements.lock`
- Modify: `infra/docker/Dockerfile.api`, `apps/api/pyproject.toml` (dev extra: `pip-tools>=7.4,<8`), `.github/workflows/ci.yml`, `infra/docker/docker-compose.dev.yml` (only if any image is still unpinned)
- Test: `apps/api/tests/test_build_lock.py`

**Interfaces:**
- Produces: `apps/api/requirements.lock` (fully pinned, hashes not required) that every later task regenerates when it changes dependencies: `cd apps/api && .venv/Scripts/python -m piptools compile --extra prod --output-file requirements.lock pyproject.toml`.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_build_lock.py
"""The API image must install exactly the locked dependency set."""
from __future__ import annotations

import pathlib
import re

API_DIR = pathlib.Path(__file__).resolve().parents[1]
REPO = API_DIR.parents[1]


def test_every_runtime_dependency_is_pinned_in_the_lock() -> None:
    lock = (API_DIR / "requirements.lock").read_text(encoding="utf-8")
    pinned = {
        m.group(1).lower().replace("_", "-")
        for m in re.finditer(r"^([A-Za-z0-9_.\-]+)==", lock, re.MULTILINE)
    }
    for name in ("fastapi", "sqlalchemy", "litellm", "celery", "asyncpg", "gunicorn"):
        assert name in pinned, f"{name} not pinned in requirements.lock"


def test_dockerfile_installs_deps_before_copying_source() -> None:
    text = (REPO / "infra" / "docker" / "Dockerfile.api").read_text(encoding="utf-8")
    lock_install = text.index("requirements.lock")
    source_copy = text.index("COPY apps/api/src")
    assert lock_install < source_copy, "dependencies must be installed before the source is copied"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q -p no:cacheprovider --junitxml=<scratch>/t1-red.xml tests/test_build_lock.py`
Expected: FAIL (`requirements.lock` missing).

- [ ] **Step 3: Implement**

1. Add `"pip-tools>=7.4,<8"` to `[project.optional-dependencies].dev`, reinstall (`pip install -e ".[dev]"`), then generate the lock with the command in Interfaces.
2. Restructure `Dockerfile.api` builder stage:

```dockerfile
WORKDIR /src
COPY apps/api/requirements.lock ./requirements.lock
RUN pip install --upgrade pip && \
    pip install --prefix=/install -r requirements.lock
COPY apps/api/pyproject.toml apps/api/README.md ./apps/api/
COPY apps/api/src ./apps/api/src
RUN pip install --prefix=/install --no-deps "./apps/api"
```

Runtime stage keeps `COPY --from=builder /install /usr/local`, the playwright install layer, and `COPY apps/api /app` (alembic files needed at runtime) — in that order.
3. CI (`.github/workflows/ci.yml`): the object-storage step uses `rustfs/rustfs:1.0.0` (MinIO images are no longer pullable); add a step that fails if `requirements.lock` is stale: `pip-compile --extra prod --output-file /tmp/lock pyproject.toml && diff <(grep -v '^#' requirements.lock) <(grep -v '^#' /tmp/lock)`.
4. Build the image once to prove the lock installs: `docker compose build api` (run in the foreground in ≤10-minute calls; re-run on timeout — cached layers resume). Then change one line of any `.py` file (and revert) and rebuild to confirm only the source layers rebuild (report the elapsed time of that second build).

- [ ] **Step 4: Verify**

Focused test passes; full suite, ruff, mypy green; `docker compose config -q` passes.

- [ ] **Step 5: Commit** — `git add apps/api/requirements.lock apps/api/pyproject.toml apps/api/tests/test_build_lock.py infra/docker/Dockerfile.api .github/workflows/ci.yml` and commit "Lock API dependencies and cache them in the Docker build".

---

### Task 2: Restore accounts and JWT auth in the API

**Files:**
- Restore from `0147bed` then adapt: `core/auth.py`, `api/v1/auth.py`, `services/user_service.py`, `services/account_email.py`, `domain/schemas/auth.py` (auth request/response models), `tests/test_auth.py`, `tests/test_account_recovery.py`.
- Modify: `api/deps.py`, `main.py`, `core/config.py`, `api/v1/notifications.py` (WebSocket `?token=`), `tests/conftest.py`, every test using `X-Test-Auth`/`signup()`.
- Delete: `services/local_workspace.py`, `tests/test_local_workspace.py`.
- Test: restored tests + `tests/test_tenant_isolation_background.py` (new; see Step 1).

**Interfaces:**
- Consumes: current `core/tenancy.set_tenant_for_session`, `domain/schemas/auth.AuthContext(user_id, tenant_id, role)`.
- Produces (exact, as at `0147bed`): `core.auth.hash_password(plain) -> str`, `verify_password(plain, hashed) -> bool`, `create_access_token(*, user_id: str, tenant_id: str, role: str = "member") -> str`, `create_refresh_token(...)`, `decode_token(token, *, expected_type: str) -> dict`, `TokenError`, `create_password_reset_token(...)`, `decode_password_reset_token(...)`, `create_email_verification_token(...)`, `decode_email_verification_token(...)`; `api.deps.get_current_user(authorization: str | None = Header(None)) -> AuthContext` (bearer JWT); routes `POST /v1/auth/signup|login|refresh|forgot-password|reset-password|verify-email|resend-verification`, `GET /v1/auth/me` (returns `UserOut` incl. `email_verified_at`). Test helpers in `tests/conftest.py`: `bearer(token) -> {"Authorization": f"Bearer {token}"}`, `async signup(client, *, email, password, tenant_name, tenant_slug=None) -> dict` calling the real `/v1/auth/signup` (as at `0147bed`).
- Settings restored: `jwt_secret`, `jwt_secret_keys`, `jwt_active_key_id`, `jwt_alg`, `jwt_access_ttl_minutes=15`, `jwt_refresh_ttl_days=30`, `password_reset_ttl_minutes=60`, `email_verification_ttl_hours=48`; production validator again requires a strong `JWT_SECRET`.

Fixes made since `0147bed` that must survive: WebSocket still works; CORS `allow_headers` must again include `Authorization`; TrustedHostMiddleware stays; `ensure_local_workspace` startup call removed from `lifespan`; no `local_workspace` references remain (`grep -rn "local_workspace\|LOCAL_TENANT_ID" apps/api` returns nothing).

- [ ] **Step 1: Write the failing tests**

Restore `tests/test_auth.py` and `tests/test_account_recovery.py` from `0147bed` (`git show 0147bed:apps/api/tests/test_auth.py > apps/api/tests/test_auth.py`, same for the other). Restore `conftest.py`'s `bearer`/`signup` helpers from `0147bed` and delete the `X-Test-Auth` override, `_test_current_user`, and the `scoped_session` fixture's `LOCAL_TENANT_ID` binding (rebind it to a tenant created via `signup`). Add:

```python
# apps/api/tests/test_auth_required.py
"""Every business endpoint requires a valid bearer token again."""
from __future__ import annotations

import httpx
import pytest

PROTECTED = [
    ("get", "/v1/leads"),
    ("get", "/v1/mailboxes"),
    ("get", "/v1/credentials"),
    ("get", "/v1/tenants/me"),
    ("post", "/v1/drafts/generate"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_protected_routes_reject_missing_token(client: httpx.AsyncClient, method: str, path: str) -> None:
    resp = await getattr(client, method)(path)
    assert resp.status_code == 401, f"{path} -> {resp.status_code}"


@pytest.mark.parametrize("path", ["/health", "/health/ready"])
async def test_health_stays_public(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run the three files. Expected: FAIL/errors (no `/v1/auth/*` routes; protected routes return 200).

- [ ] **Step 3: Implement**

1. `git show 0147bed:<path>` for each file under Files → Restore; adapt imports to today's modules (e.g. errors moved/removed: `AuthError` must be re-added to `core/errors.py` and mapped to 401 in `main.py`).
2. Remove Microsoft pieces while restoring (sign-in providers list only `google`).
3. `api/deps.py`: restore the JWT `_bearer_token` + `get_current_user` from `0147bed`; keep `get_db`/`get_scoped_db`.
4. `main.py`: re-include `auth.router`; remove `ensure_local_workspace` from lifespan; CORS `allow_headers=["Authorization", "Content-Type"]`.
5. Notifications WebSocket: restore `?token=` validation from `0147bed`.
6. Delete `services/local_workspace.py`, `tests/test_local_workspace.py`; replace every `LOCAL_TENANT_ID` use in tests with tenants created by `signup()` (tests that need "the" tenant create one). `workers/tasks/inbox.py` is rewritten in Task 4 — in this task make it compile by selecting mailboxes across all active tenants (per-tenant `set_tenant_for_session` before each mailbox), keeping its current per-mailbox session design.
7. Restore per-IP auth rate limits (`login`, `signup`, `refresh`, `password_reset`) exactly as at `0147bed`; conftest raises them for tests as it did then.

- [ ] **Step 4: Verify** — restored + new tests pass; full suite green (tenancy isolation tests now use real tokens); ruff, mypy clean; `grep` from Fixes returns nothing.

- [ ] **Step 5: Commit** "Restore accounts, JWT auth and tenant-scoped requests".

---

### Task 3: Google sign-in and the web auth flow

**Files:**
- Restore from `0147bed` then adapt: `services/social_auth.py`, `services/social_login_service.py`, `tests/test_social_login.py` (Google cases only).
- Restore from `d0dd2cd^` (web, before auth removal) then adapt: `apps/web/src/app/(auth)/{login,signup,forgot-password,reset-password,verify-email,oauth/callback}/page.tsx`, `apps/web/src/app/(auth)/layout.tsx`, `apps/web/src/lib/auth.tsx`, `apps/web/src/components/auth/social-buttons.tsx` (Google only), `apps/web/src/components/account/verify-email-banner.tsx`.
- Modify: `apps/web/src/lib/api-client.ts` (restore token header, refresh-on-401, auth methods from `d0dd2cd^`), `apps/web/src/components/providers.tsx`, `apps/web/src/components/nav/sidebar.tsx` (user email + sign out + login redirect), `apps/web/src/app/(app)/layout.tsx` (verify banner), `apps/web/src/app/page.tsx` (redirect `/dashboard` if signed in else `/login`), `apps/web/src/app/(app)/notifications/page.tsx` (`?token=`).
- Test: `tests/test_social_login.py`; web gates.

**Interfaces:**
- Consumes: Task 2 routes and tokens.
- Produces: `GET /v1/auth/oauth/providers` → `[{"provider": "google", "label": "Google"}]` when `GOOGLE_OAUTH_CLIENT_ID` is set, else `[]`; `GET /v1/auth/oauth/google/start` → `{"auth_url": ...}`; `GET /v1/auth/oauth/google/callback` → redirects to `${WEB_BASE_URL}/oauth/callback#access_token=...&refresh_token=...` (as at `0147bed`). Settings: `google_oauth_client_id`, `google_oauth_client_secret`, `google_login_redirect_uri` (default `http://localhost:8000/v1/auth/oauth/google/callback`), `web_base_url`.

Fixes made since that must survive in web: no billing/pricing/landing page (landing stays removed); no Microsoft button; sidebar keeps Task 7/8 nav (no Billing, no CRM); integrations and mailboxes pages from Task 8 stay (integrations gets key entry back in Task 5).

- [ ] **Step 1: Write the failing test** — restore `tests/test_social_login.py` from `0147bed`, delete Microsoft cases, run. Expected: FAIL (no oauth routes).
- [ ] **Step 2: Implement** — restore/adapt the files above; Google only.
- [ ] **Step 3: Verify** — social login tests pass; full API suite green; `grep -rni "microsoft" apps/api/src apps/web/src` returns only unrelated matches (list them); web lint/typecheck/build pass; manually confirm with the dev stack: `npm run dev:web` → `/login` renders, signup creates an account and lands on `/dashboard`, sign-out returns to `/login`.
- [ ] **Step 4: Commit** "Restore Google sign-in and the web sign-in flow".

---

### Task 4: Fan-out background jobs and idempotent, lock-safe sending

**Files:**
- Create: `workers/tasks/fanout.py`, `tests/test_fanout.py`, `tests/test_send_idempotency.py`
- Modify: `workers/celery_app.py`, `workers/tasks/inbox.py`, `workers/tasks/send.py`, `workers/tasks/send_tasks.py`, `workers/tasks/scrape.py`, `workers/tasks/__init__.py`, `services/send_service.py`, `core/config.py`, `alembic/versions/0019_public_launch.py` (create; this task adds the step status value if constrained — see Step 3.4)

**Interfaces:**
- Produces:
  - Celery tasks (registered name → Python function): `outreach_os.workers.enqueue_mailbox_polls` → `fanout.enqueue_mailbox_polls` (beat); `outreach_os.workers.poll_mailbox` → `workers.tasks.inbox.poll_mailbox_task(tenant_id: str, mailbox_id: str) -> dict[str, int]` (named `poll_mailbox_task` so it does not shadow the service function `services.mailbox.inbox.poll_mailbox`); `outreach_os.workers.enqueue_due_sends` → `fanout.enqueue_due_sends` (beat); `outreach_os.workers.send_due_tenant` → `workers.tasks.send_tasks.send_due_tenant(tenant_id: str) -> dict[str, int]`. `fanout.py` imports `poll_mailbox_task` and `send_due_tenant` into its namespace (tests patch `fanout.poll_mailbox_task.delay` / `fanout.send_due_tenant.delay`). The old `poll_inboxes`/`send_due` names stay registered as thin aliases that call the dispatchers (so already-queued messages still run).
  - `celery_app.conf.task_default_queue = "default"`; `task_routes = {"outreach_os.scrape.run_job": {"queue": "scrape"}}`.
  - Settings: `scrape_task_soft_time_limit_seconds: int = 900`, `scrape_task_time_limit_seconds: int = 960`, `send_claim_stale_minutes: int = 15`, `broker_visibility_timeout_seconds: int = 3600`.
  - `SequenceStep.status` gains `"sending"`; a step in `sending` older than `send_claim_stale_minutes` is marked `failed` with `stop_reason="send outcome unknown (worker stopped mid-send)"` and is never re-sent automatically.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_fanout.py
"""Beat dispatchers enqueue one task per mailbox / per workspace."""
from __future__ import annotations

import pytest

from tests.conftest import bearer, signup


async def test_mailbox_polls_fan_out_one_task_per_imap_mailbox(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from outreach_os.workers.tasks import fanout

    a = await signup(client, email="fa@example.com", password="pw-12345-AbCde", tenant_name="A")
    b = await signup(client, email="fb@example.com", password="pw-12345-AbCde", tenant_name="B")
    for acct, addr in ((a, "a-box@example.com"), (b, "b-box@example.com")):
        resp = await client.post(
            "/v1/mailboxes/smtp",
            headers=bearer(acct["access_token"]),
            json={"email_address": addr, "host": "smtp.example.com", "port": 587, "username": addr,
                  "password": "pw", "use_tls": True, "imap_host": "imap.example.com"},
        )
        assert resp.status_code == 201, resp.text

    enqueued: list[tuple[str, str]] = []
    monkeypatch.setattr(fanout.poll_mailbox_task, "delay", lambda t, m: enqueued.append((t, m)))
    count = await fanout.enqueue_mailbox_polls_async()

    assert count == 2
    assert {t for t, _ in enqueued} == {a["tenant_id"], b["tenant_id"]}


async def test_due_sends_fan_out_one_task_per_active_workspace(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from outreach_os.workers.tasks import fanout

    a = await signup(client, email="sa@example.com", password="pw-12345-AbCde", tenant_name="SA")
    enqueued: list[str] = []
    monkeypatch.setattr(fanout.send_due_tenant, "delay", lambda t: enqueued.append(t))
    await fanout.enqueue_due_sends_async()
    assert a["tenant_id"] in enqueued
```

```python
# apps/api/tests/test_send_idempotency.py
"""A step can be sent at most once, even with concurrent or redelivered tasks."""
from __future__ import annotations

# Build a due SequenceStep with a ready draft using the helpers in
# tests/test_phase4_send.py (read it; reuse its setup functions). Then:
#
# 1. test_concurrent_passes_send_a_step_once:
#    run two `SendService(session).execute_due(tenant_id=...)` passes in two
#    separate sessions concurrently (asyncio.gather), each with its own
#    recording StubMailer; assert exactly one message was sent in total and
#    the step status is "sent".
#
# 2. test_redelivered_task_skips_a_step_already_claimed:
#    set the step to status="sending" with claimed_at=now (commit), run a pass,
#    assert nothing was sent and the step is still "sending".
#
# 3. test_stale_claim_is_failed_not_resent:
#    set status="sending", claimed_at=now - 16 minutes, run a pass, assert
#    nothing was sent, status == "failed",
#    stop_reason == "send outcome unknown (worker stopped mid-send)".
```

(Write these three tests as real code using the phase-4 helpers; the comments above are the required assertions.)

- [ ] **Step 2: Run to verify failure** — Expected: FAIL (`fanout` missing; concurrent pass sends twice or `claimed_at` missing).

- [ ] **Step 3: Implement**

1. `workers/tasks/fanout.py`: `enqueue_mailbox_polls_async()` selects `(tenant_id, id)` of active SMTP mailboxes with IMAP configured across all active tenants (tenant table is not RLS-protected; for mailbox rows, iterate tenants and bind each tenant before selecting its mailboxes), calls `poll_mailbox.delay(str(tenant_id), str(mailbox_id))` per mailbox, returns the count. `enqueue_due_sends_async()` selects active tenant ids that have at least one due `pending`/`queued` step (bind each tenant; `EXISTS` query) and enqueues `send_due_tenant.delay(str(tid))`. Celery wrappers use `run_worker_task`. Beat schedule: replace the `send_due`/`poll_inboxes` entries with `enqueue_due_sends` and `enqueue_mailbox_polls`, same intervals and `expires`.
2. `workers/tasks/inbox.py`: `poll_mailbox_task(tenant_id, mailbox_id)` (registered as `outreach_os.workers.poll_mailbox`) = today's per-mailbox body (fresh session, bind tenant, `session.get`, `poll_mailbox(...)`, commit) with the guard catching `Exception` **but re-raising** `celery.exceptions.SoftTimeLimitExceeded`. Keep `poll_inboxes` as an alias that calls `enqueue_mailbox_polls_async()`.
3. `services/send_service.py` claim protocol in `execute_due`:
   - Select due steps with `.with_for_update(skip_locked=True)`.
   - For each step: set `status="sending"`, `claimed_at=utcnow()`, **commit** (so the claim survives a crash), then run `execute_step`, then commit the final status.
   - Before selecting, mark stale claims (`status="sending"` and `claimed_at < now - send_claim_stale_minutes`) as failed with the exact `stop_reason` above.
   - `execute_due` therefore owns commits; callers pass a session they do not otherwise use.
4. Migration `0019_public_launch.py`: add `sequence_step.claimed_at TIMESTAMP NULL`; if `sequence_step.status` has a CHECK constraint (inspect the model/migrations), recreate it including `'sending'`. (Tasks 6/7 add more columns to this same migration file — create it here; later tasks append.)
5. `celery_app.py`: `task_default_queue="default"`, `task_routes` as in Interfaces, `broker_transport_options={"visibility_timeout": settings.broker_visibility_timeout_seconds}`.
6. `workers/tasks/scrape.py`: the Celery task declares `soft_time_limit=settings.scrape_task_soft_time_limit_seconds`, `time_limit=settings.scrape_task_time_limit_seconds`; catch `SoftTimeLimitExceeded` around the join and mark the job failed via the existing `_mark_job_failed_async` path.
7. Compose (`docker-compose.yml`): the `worker` service consumes `-Q default`; add a `worker-scrape` service (same image) with `-Q scrape --concurrency 1`.

- [ ] **Step 4: Verify** — new tests pass; existing inbox/send/scrape tests pass (update any that called removed internals); full suite, ruff, mypy green; `docker compose config -q`.
- [ ] **Step 5: Commit** "Fan out polling and sending per mailbox/workspace and make sends idempotent".

---

### Task 5: Bring-your-own keys in the app; env keys only for self-hosting

**Files:**
- Modify: `core/config.py` (`allow_env_provider_keys: bool = False`; production validator), `services/llm_credentials.py` (`env_credentials` returns `None` unless allowed), `services/credential_lookup.py` (env overlay only if allowed), `api/v1/credentials.py` (listing reports env status only if allowed), `services/onboarding_service.py` (llm step text: "Add your API key under Integrations"), `apps/web/src/app/(app)/integrations/page.tsx` (restore key-entry UI from `36c4c22^`, keep Test button), `apps/web/src/lib/api-client.ts` (restore `createCredential`/`deleteCredential`/`testCredential`), `apps/web/src/components/settings/model-picker.tsx` (wording).
- Test: `tests/test_env_keys.py` (update), `tests/test_byok_credentials.py` (restore stored-key precedence as primary path), `tests/test_config_production.py`.

**Interfaces:**
- Consumes: existing `POST /v1/credentials` (kind, label, secret_payload), `POST /v1/credentials/{id}/test`.
- Produces: `settings.allow_env_provider_keys`; with it `False`, `env_credentials(p)` → `None` and `get_credential_secrets` ignores env.

- [ ] **Step 1: Failing tests**

```python
# add to apps/api/tests/test_env_keys.py
async def test_env_keys_ignored_unless_self_hosting_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from outreach_os.core.config import get_settings
    from outreach_os.services import llm_credentials

    monkeypatch.setenv("GROQ_API_KEY", "gsk-env-test")
    env_keys.reset_env_cache()
    monkeypatch.setattr(get_settings(), "allow_env_provider_keys", False)
    assert llm_credentials.env_credentials("groq") is None
    monkeypatch.setattr(get_settings(), "allow_env_provider_keys", True)
    assert llm_credentials.env_credentials("groq") is not None
```

```python
# add to apps/api/tests/test_config_production.py
def test_production_rejects_env_provider_keys(monkeypatch) -> None:
    # Build Settings from real env vars the way the other tests in this file do,
    # with ENVIRONMENT=production and every other required value valid, plus
    # ALLOW_ENV_PROVIDER_KEYS=true. Assert a ValueError mentioning
    # "ALLOW_ENV_PROVIDER_KEYS".
```

(Write the second as real code following that file's existing pattern.) Existing env-key tests that expect env keys to work must set `allow_env_provider_keys=True` explicitly.

- [ ] **Step 2: RED**, **Step 3: implement**, **Step 4: verify** (full suite, ruff, mypy, web gates; the integrations page lets a user paste a key, save, test, delete).
- [ ] **Step 5: Commit** "Keys come from each workspace; env keys only for opt-in self-hosting".

---

### Task 6: Correct, compliant campaign email

**Files:**
- Create: `core/signing.py`, `tests/test_campaign_email.py`
- Modify: `core/mailer.py` (`OutgoingMessage.body_html: str | None = None`, `headers: dict[str, str] = field(default_factory=dict)`; `SmtpMailer` sends `multipart/alternative` when `body_html` is set and applies `headers`), `services/send_service.py`, `api/v1/tracking.py`, `api/v1/tenants.py` + `domain/schemas/tenant.py` (postal address), `core/config.py` (`link_signing_secret: SecretStr`, required and ≥ 32 chars in production), `alembic/versions/0019_public_launch.py` (append `tenant.postal_address TEXT NULL`), `.env.example`, `scripts/init-env.mjs` (generate `LINK_SIGNING_SECRET` and `JWT_SECRET` when blank)

**Interfaces:**
- Produces: `core.signing.sign(payload: dict[str, str]) -> str`, `core.signing.verify(token: str) -> dict[str, str]` (raises `SigningError`); HMAC-SHA256 over compact JSON with `link_signing_secret`, URL-safe base64, no expiry. Unsubscribe URL `/t/unsubscribe?t=<token>` where payload `{"tid": tenant_id, "em": lead_email}`; `GET` shows a confirmation page, `POST` (RFC 8058 one-click) unsubscribes. `TenantOut.postal_address: str | None`; `PATCH /v1/tenants/me` accepts `postal_address`.

Required behaviour (each is a test in `tests/test_campaign_email.py`; build a due step with a ready draft via the phase-4 helpers):
1. The sent email's text body is the **full** draft body loaded from object storage (`download_text(settings.s3_drafts_bucket, draft.s3_key)`), not `body_preview`; if the object is missing the step fails with `stop_reason="draft body unavailable"`.
2. The message is `multipart/alternative`: plain-text part has no `<img>`; HTML part has the tracking pixel whose URL contains the **real** `Send.id`, and `GET /t/open/{send.id}.png` records an open for that send.
3. Headers: `List-Unsubscribe: <{PUBLIC_BASE_URL}/t/unsubscribe?t=...>` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click`; `Message-ID` domain equals the sender mailbox's domain.
4. The footer contains the workspace `postal_address`; a workspace with no postal address cannot send: `execute_step` fails the step with `stop_reason="postal address required"` and `POST /v1/sequences` returns 428 with that message.
5. `POST /t/unsubscribe?t=<valid>` adds the lead email to that workspace's suppression list; a tampered token returns 400 and suppresses nothing; the old `?email=&tenant=` form returns 400.
6. A follow-up step's message has `In-Reply-To` and `References` set to the previous send's `Message-ID` in the same sequence run.

- [ ] Steps: write the six tests (real code) → RED → implement → verify (full suite, ruff, mypy) → commit "Send the full draft as compliant, threaded multipart email with signed unsubscribe".

---

### Task 7: Usage limits, warm-up, bounces, verification gate, suspension

**Files:**
- Create: `services/usage_limits.py`, `services/mailbox/warmup.py`, `services/mailbox/bounces.py`, `tests/test_usage_limits.py`, `tests/test_warmup.py`, `tests/test_bounces.py`
- Modify: `core/config.py` (limit settings from Global Constraints; `warmup_start_per_day=10`, `warmup_step_per_day=10`, `hard_bounce_pause_threshold=3`), `core/errors.py` (`UsageLimitExceeded` → HTTP 429 in `main.py`), `services/send_service.py`, `services/reply_service.py` (bounce path), `api/v1/{leads,mailboxes,scraping_jobs,drafts,sequences}.py`, `alembic/versions/0019_public_launch.py` (append `mailbox.hard_bounce_count INTEGER NOT NULL DEFAULT 0`, `mailbox.paused_reason TEXT NULL`), `api/v1/tenants.py` (`GET /v1/tenants/me/usage`)

**Interfaces:**
- Produces: `usage_limits.check(session, *, tenant_id: uuid.UUID, limit: Literal["sends_per_day","leads_per_month","concurrent_scrapes","mailboxes","drafts_per_hour"], adding: int = 1) -> None` (raises `UsageLimitExceeded(limit, used, allowed)`); `usage_limits.record(session, *, tenant_id, metric: str, quantity: int = 1, source: str, source_id: uuid.UUID | None)` using the existing `usage_event` model; `usage_limits.snapshot(session, *, tenant_id) -> dict[str, dict[str, int]]` (`{"sends_per_day": {"used": n, "allowed": m}, ...}`); `warmup.effective_daily_cap(mailbox, *, today: date) -> int` = `min(mailbox.daily_send_cap, start + step * days_since_created)`; `bounces.is_hard_bounce(data: ReplyIngestIn) -> bool` (DSN `multipart/report` or `Status: 5.x.x`, or `mailer-daemon`/`postmaster` sender with a 5xx line).
- `GET /v1/tenants/me/usage` returns the snapshot.

Required behaviour (tests):
1. Each limit returns HTTP 429 with a message naming the limit at the boundary (sends via `execute_due` defers the step instead: status stays `queued`, no 429).
2. Warm-up: a mailbox created today sends at most 10; created 3 days ago at most 40; never above its configured cap.
3. A campaign can't send until the owner's email is verified: `POST /v1/sequences` returns 403 `"verify your email before sending"`.
4. A suspended workspace (`tenant.status="suspended"`): `send_due_tenant` sends nothing, scraping jobs are rejected (403), `enqueue_due_sends` skips it.
5. Hard bounce: the lead is suppressed; the mailbox's `hard_bounce_count` increments; at `hard_bounce_pause_threshold` the mailbox is deactivated with `paused_reason="too many hard bounces"` and a `send.bounced` notification is published.

- [ ] Steps: tests (real code) → RED → implement → verify → commit "Per-workspace usage limits, mailbox warm-up, bounce handling and suspension".

---

### Task 8: Account self-service and the operator admin console

**Files:**
- Restore from `3900e8d^` (before SaaS removal) then adapt: `api/v1/admin.py`, `domain/schemas/admin.py`, `tests/test_admin_console.py` (drop billing/MRR fields and plan assertions); `api/deps.py` `require_platform_admin`, `get_admin_db`.
- Restore from `d0dd2cd^`: `apps/web/src/app/(app)/admin/page.tsx` (drop billing columns).
- Modify: `api/v1/users.py` (restore only `GET /v1/users/me`, `POST /v1/users/me/password`, `DELETE /v1/users/me`), `api/v1/gdpr.py` (keep export; delete goes through users), `apps/web/src/app/(app)/settings/page.tsx` (change password, delete account with typed confirmation + password re-entry, postal address field, usage table from `/v1/tenants/me/usage`), `apps/web/src/components/nav/sidebar.tsx` (admin link for platform admins), `apps/web/src/lib/api-client.ts`.
- Test: `tests/test_account_self_service.py` (new), restored `tests/test_admin_console.py`.

**Interfaces:**
- Produces: `POST /v1/users/me/password {current_password, new_password}` → 204 (Google-only accounts: 400 "no password set"); `DELETE /v1/users/me {password}` (or `{confirm: "DELETE"}` for Google-only accounts plus a fresh token issued within 10 minutes) → 204, deletes the tenant and all its rows (cascade via FKs or explicit deletes per table, inside RLS scope) and the user; S3 objects under the tenant prefix deleted. Admin: `GET /v1/admin/customers`, `GET /v1/admin/stats`, `PATCH /v1/admin/customers/{tenant_id}/status {status: "active"|"suspended"}`.

Required behaviour (tests): password change works and the old password stops working; deleting account A removes every row with `tenant_id=A` (assert zero rows in each tenant table, queried as the superuser) and leaves account B untouched; a non-admin gets 404 on `/v1/admin/*`; suspend then unsuspend round-trips and suspension blocks sending (reuse Task 7's check).

- [ ] Steps: tests → RED → implement → verify (API + web gates) → commit "Account self-service and the operator admin console".

---

### Task 9: Production configuration, observability and deploy files

**Files:**
- Create: `render.yaml`, `docs/deploy.md`, `apps/web/sentry.client.config.ts`, `apps/web/sentry.server.config.ts`, `apps/api/src/outreach_os/core/request_id.py`, `tests/test_production_config.py`
- Modify: `core/config.py`, `main.py`, `workers/celery_app.py` (Sentry Celery integration when `SENTRY_DSN` set), `core/logging.py` (request id in every log line), `apps/web/next.config.mjs` (Sentry wrap; CSP `connect-src` includes the API origin and Sentry ingest), `apps/web/package.json` (`@sentry/nextjs`), `.env.example`

**Interfaces:**
- Produces: effective allowed hosts = `ALLOWED_HOSTS` ∪ {hostname of `PUBLIC_BASE_URL`}; production validator requires: strong `JWT_SECRET`, `LINK_SIGNING_SECRET` ≥ 32 chars, `VAULT_MASTER_KEY`, `INBOUND_WEBHOOK_SECRET`, `CORS_ALLOWED_ORIGINS` non-empty, `PUBLIC_BASE_URL` non-localhost https, `WEB_BASE_URL` https, `ALLOW_ENV_PROVIDER_KEYS=false`, `CELERY_TASK_ALWAYS_EAGER=false`, `S3_ENDPOINT_URL` set, `SMTP_HOST` set. `X-Request-ID` echoed on every response (generated if absent).
- `render.yaml` services: `outreach-api` (web, Docker, `infra/docker/Dockerfile.api`, `numInstances: 2`, autoscaling min 2 max 6 target CPU 70%, `preDeployCommand: alembic upgrade head`, health check `/health/ready`), `outreach-worker` (worker, `celery ... worker -Q default --concurrency 4`, autoscaling min 1 max 8), `outreach-worker-scrape` (worker, `-Q scrape --concurrency 1`, plan with ≥ 2 GB RAM, min 1 max 3), `outreach-beat` (worker, `celery ... beat`, exactly 1 instance), `outreach-db` (Postgres 16), `outreach-redis` (key-value); an env group `outreach-shared` with every non-secret setting and `sync: false` placeholders for every secret. `DATABASE_POOL_SIZE=5`, `DATABASE_MAX_OVERFLOW=5` per instance.

Required behaviour (tests in `tests/test_production_config.py`, constructing `Settings` from real env vars like `test_config_production.py`): a request with `Host` equal to `PUBLIC_BASE_URL`'s hostname is accepted even when `ALLOWED_HOSTS` omits it; each missing/invalid production requirement above yields a validation error naming it; responses carry `X-Request-ID`.

`docs/deploy.md`: step-by-step for the owner — Render blueprint deploy, Vercel project (root directory `apps/web`, `NEXT_PUBLIC_API_URL`), R2 buckets (`outreach`, `outreach-drafts`) and token, Resend SMTP (`smtp.resend.com:587`), Google OAuth app (authorised redirect URI `https://api.<domain>/v1/auth/oauth/google/callback`, JavaScript origin `https://app.<domain>`), Sentry DSNs, DNS records, the RLS privileged bootstrap SQL (roles + `ALTER FUNCTION auth_user_by_email ... OWNER TO <bypassrls role>`) and the feasibility check to run first, backups/restore drill, rotating secrets.

- [ ] Steps: tests → RED → implement → verify (API + web gates; `docker compose config -q`; a Render blueprint schema check if the CLI is available, otherwise a YAML parse) → commit "Production config, observability and Render/Vercel deploy files".

---

### Task 10: Terms, acceptable use, and the authenticated end-to-end smoke test

**Files:**
- Create: `apps/web/src/app/(legal)/terms/page.tsx`, `apps/web/src/app/(legal)/acceptable-use/page.tsx`, `apps/web/src/app/(legal)/layout.tsx`
- Modify: `apps/web/src/app/(auth)/signup/page.tsx` (required checkbox "I agree to the Terms and Acceptable Use Policy" with links), `docker-compose.yml` (dev/e2e: `SMTP_HOST=greenmail`, `SMTP_PORT=3025` so verification email lands in GreenMail), `scripts/e2e_smoke.py`, `README.md`, `SETUP.md`, `docs/runbook.md`

Legal page wording: a clearly marked template (headings: acceptance, accounts, acceptable use — no purchased/scraped-without-consent lists for spam, comply with CAN-SPAM/GDPR/CASL, no impersonation, honour unsubscribes — user content and keys, suspension, disclaimer, contact) with a visible banner "Template — have this reviewed before launch", because the owner must approve final wording.

Smoke (`scripts/e2e_smoke.py`, stdlib only, `--api`/`--imap-host` flags so it can target staging):
1. Health.
2. Sign up account A and account B via `/v1/auth/signup`; read each verification email from GreenMail over IMAP; call `/v1/auth/verify-email`.
3. A: set postal address; add its Groq key via `POST /v1/credentials` if `--groq-key-env` names an env var that is set (else SKIP LLM checks); create ICP; import CSV lead; create SMTP+IMAP mailbox on GreenMail; send-test delivered.
4. A (LLM present): campaign → draft → sequence → wait for send → verify received message is multipart with full body, `List-Unsubscribe` header, postal address → reply over SMTP with `In-Reply-To` → wait for the reply to appear via `/v1/replies`.
5. A: `POST` one-click unsubscribe from the received `List-Unsubscribe` URL → lead suppressed.
6. Isolation: B lists leads, mailboxes, drafts, credentials, replies → all empty; B requesting A's draft id → 404.
7. Usage: `GET /v1/tenants/me/usage` for A shows the sends counted.
8. B deletes its account → B's token no longer works.

- [ ] Steps: implement → run the smoke against the local stack (`npm run setup`, `docker compose --profile e2e up -d --build`, `python scripts/e2e_smoke.py --groq-key-env OUTREACH_TEST_GROQ_KEY`) → web gates → docs updated → commit "Legal pages, authenticated two-account smoke test, updated docs".

---

## Out of this plan (Phase 2/3 plan, written when accounts exist)

Render/Vercel/R2/Resend/Sentry provisioning, the RLS feasibility check on Render Postgres, DNS, staging deploy, load test (~200 simulated users + concurrent mailbox polls), launch checklist, production cut-over.
