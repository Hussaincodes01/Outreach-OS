# Single-user, end-to-end Outreach OS — Design

Status: approved by the project owner on 2026-09-13 (decisions below were chosen
explicitly). This spec is the binding authority for the implementation plan
`docs/superpowers/plans/2026-09-13-single-user-e2e.md`.

## Problem

1. The project does not build end to end. `pip install` of `apps/api` fails in
   both Docker and native installs because `apps/api/pyproject.toml` declares
   `readme = "../../README.md"`, which current hatchling rejects
   ("Readme path must be within the project directory"). The API, worker,
   beat and migrate images therefore cannot be built.
2. The product is a multi-tenant SaaS gated behind signup/login/JWT. The owner
   wants a single-user tool that opens straight into the app.
3. Several paths look like they work but do not deliver real results:
   - Campaign sends go through the platform mailer (`get_mailer_client()`),
     which is a `StubMailer` unless `SMTP_HOST` is set — the mailbox's own SMTP
     credentials are never used for sequence sends.
   - `outreach_os.workers.send_due` exists but is not on the Celery beat
     schedule, so due sequence steps are never sent.
   - Gmail/Outlook mailbox "sending" is a stub that reports success.
   - Replies can only arrive through the HMAC webhook; nothing reads a real
     inbox.
   - Draft bodies are stored in S3, but the production compose stack has no
     S3/MinIO service.

## Decisions (made by the owner)

| Topic | Decision |
|---|---|
| Auth | **Single built-in workspace.** No signup, login, JWT, password reset, email verification, social login, team users or roles. Every request acts as one auto-created local workspace. PostgreSQL RLS stays in place underneath, bound to that workspace. |
| Provider keys | **`.env` file.** LLM and scraping keys are read from environment variables / `.env`. The web UI shows which providers are configured and can test them; it does not collect keys. |
| SaaS extras | **Removed:** billing, plans and plan caps, usage-limit enforcement, platform admin console, marketing landing/pricing page, team users/roles. Opening the web app lands on the dashboard. |
| Run mode | **Docker Compose, one command** from the repo root brings up everything (postgres, redis, minio, migrate, api, worker, beat, web). Host ports must not collide with other local stacks on 5432/6379. |

## Requirements

### R1 Build
- `pip install ./apps/api` succeeds (Docker and native).
- All images build; `docker compose up -d --build` from the repo root starts a
  healthy stack; `/health` and `/health/ready` return ok; web serves on 3000.

### R2 No authentication
- No endpoint requires an `Authorization` header. Auth endpoints
  (`/v1/auth/*`), team users (`/v1/users`), admin (`/v1/admin/*`) and billing
  (`/v1/billing/*`) are removed.
- A fixed local workspace (tenant + owner user) is created idempotently at
  startup and on first use. Fixed identifiers:
  - `LOCAL_TENANT_ID = 00000000-0000-4000-8000-000000000001`
  - `LOCAL_USER_ID   = 00000000-0000-4000-8000-000000000002`
  - tenant slug `local`, tenant name `My Workspace`, user email `owner@example.com`, role `owner`.
- The notifications WebSocket accepts connections without a token.
- Public endpoints (tracking pixel, unsubscribe, inbound webhook) keep working.
- RLS stays enforced: the app still connects as the non-superuser role and
  binds `app.current_tenant` to the local workspace on every scoped session.

### R3 Keys from `.env`
- LLM provider key env var: `<PROVIDER>_API_KEY`; base URL: `<PROVIDER>_API_BASE`,
  where `<PROVIDER>` is `ProviderSpec.provider` upper-cased with every
  non-alphanumeric character replaced by `_`.
- Scraping key env var: `<KIND>_API_KEY` for kinds `serper`, `proxycurl`,
  `rapidapi`, `scrapingbee` (e.g. `SERPER_API_KEY`).
- Values are read from the process environment first, then from the `.env`
  file Settings reads. Empty values count as unset.
- A key present in the environment takes precedence over any stored
  credential row.
- Missing LLM key still fails with `428` (no fabricated output).
- The provider catalogue reports env-configured providers as connected; a test
  action makes a real probe call against the env key.
- Onboarding treats an env-configured provider as "connected", and a
  successful test as "verified".

### R4 Real sending
- Sequence sends use the sending mailbox's own SMTP credentials.
- `send_due` runs on the beat schedule every `SEND_DUE_INTERVAL_SECONDS`.
- Gmail/Outlook OAuth mailboxes are removed (API + UI). SMTP (which works with
  Gmail/Outlook app passwords) is the supported transport.

### R5 Real reply capture
- SMTP mailboxes may carry IMAP settings (host, port, SSL). A beat task polls
  unseen messages and feeds them to `ReplyService.ingest`, which matches them
  to the original send by `In-Reply-To`/`References`.
- The inbound webhook remains as an alternative.

### R6 Storage
- The compose stack includes MinIO and creates the buckets; drafts store and
  load bodies without error.

### R7 Web
- No login/signup/reset/verify/oauth pages, no auth context, no bearer tokens.
- No billing, admin, landing/pricing pages or links.
- `/` redirects to `/dashboard`.
- Integrations page: per provider shows configured / not configured (from the
  API), the env var name to set, and a Test button. No key entry form.
- Mailboxes page: add SMTP mailbox with optional IMAP fields; no Gmail/Outlook
  OAuth buttons.
- `lint:web`, `typecheck:web`, `build:web` pass.

### R8 Verification
- API: `ruff check .`, `mypy src`, `pytest` pass (auth/billing/admin/social
  tests removed; tenancy-isolation tests kept via a test-only auth override).
- An end-to-end smoke script runs against the live compose stack and proves:
  health, onboarding status, ICP create, CSV lead import, SMTP mailbox create
  against a local test mail server, a real SMTP delivery captured by that
  server, IMAP reply capture, and (when an LLM key is configured) draft
  generation.
- README, SETUP and runbook describe the single-user flow.

## Out of scope (documented as known limitations)
- CRM (Google Sheets) sync and calendar provider clients remain stubs; the CRM
  sync page is removed from navigation.
- Dropping now-unused database tables (plan, subscription, usage_event,
  billing_portal_token). They stay; nothing reads them.
