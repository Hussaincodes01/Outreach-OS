# Public multi-user launch — Design

Status: approved section by section by the owner on 2026-09-29. This spec
supersedes the single-user decisions in
`2026-09-13-single-user-e2e-design.md` wherever they conflict (auth,
key storage, SaaS operator tools). Everything else from that work (the build
fix, per-mailbox SMTP sending, IMAP reply capture, worker event-loop fix,
one-command Docker stack, Host allowlist, rate-limit retries, Groq catalogue,
draft endpoint fix) carries forward.

## Goal

Deploy Outreach OS publicly so anyone can sign up and use it, safely and
reliably, at a scale of 1,000+ users soon after launch.

## Decisions (made by the owner)

| Topic | Decision |
|---|---|
| Audience | Public sign-up. Each user gets a private workspace. |
| AI keys | Bring your own: each user adds their own provider keys in the app. The operator's keys are never used for users. |
| Scale target | 1,000+ users within months: horizontal scaling from day one. |
| Hosting | Web on Vercel. API, workers, scheduler, managed Postgres (pgvector) and managed Redis on Render. Object storage on Cloudflare R2. Transactional email via Resend (SMTP). Error monitoring via Sentry. |
| Sign-in | Email + password (with verification and reset) and "Sign in with Google". |
| Pricing | Free beta with per-workspace usage limits. Stripe billing is a later phase. |
| Approach | Restore the original account system from git history (commit `0147bed` and earlier) on top of current code; keep all fixes made since. |

## 1. Architecture and deployment

| Component | Where | Scaling |
|---|---|---|
| Web (Next.js) | Vercel | Automatic. Calls the API at `https://api.<domain>`. |
| API (FastAPI, gunicorn + uvicorn workers) | Render web service (Docker) | ≥ 2 instances, autoscale on CPU/memory. Stateless. |
| Worker, queue `default` (send, inbox poll, draft, notifications) | Render background worker | Many small instances. |
| Worker, queue `scrape` (headless-browser scraping) | Render background worker | Fewer, larger instances, scaled independently. |
| Scheduler (Celery beat) | Render background worker | Exactly one instance. |
| Postgres + pgvector | Render managed Postgres | Daily backups + point-in-time recovery. RLS unchanged. |
| Redis | Render managed Redis | Celery broker/results + rate-limit counters. |
| Object storage | Cloudflare R2 (S3-compatible) | Replaces MinIO in production. |
| Transactional email | Resend over SMTP | Verification, reset, digests. |
| Outreach email | Each user's own SMTP/IMAP mailbox | Never sent from platform IPs. |
| Monitoring | Sentry (API, workers, web) + uptime check | Alerts. |

Required scaling changes:
- **Inbox polling fans out.** The beat task enqueues one `poll_mailbox` task per
  active IMAP mailbox across all workspaces, instead of one task polling every
  mailbox serially.
- **Sending fans out** per workspace, so one heavy workspace cannot delay others.
- **Connection pooling** sized per instance (`DATABASE_POOL_SIZE`,
  `DATABASE_MAX_OVERFLOW`) so autoscaling cannot exhaust Postgres connections.
- **Migrations run as a one-off pre-deploy step**, never at app start.
- **Two Celery queues** (`default`, `scrape`) with task routing.

Feasibility risk (first task of the build): the RLS setup relies on one
privileged step (migration `0010` makes `auth_user_by_email` a
`SECURITY DEFINER` function owned by a role that bypasses RLS, and the app
connects as a separate `NOSUPERUSER NOBYPASSRLS` role). Verify on Render
managed Postgres that (a) a separate app role can be created and (b) the
login lookup function can bypass RLS. If not, adapt the mechanism; if no
mechanism works on Render, move only the database to Neon.

## 2. Accounts and tenant isolation

- **Restore from git history:** signup, login, refresh, email verification,
  password reset, Google sign-in (`/v1/auth/*`), JWT issuance/verification with
  key rotation, per-IP auth rate limits, web auth pages and auth context.
- Signup creates a new workspace (tenant) with the user as owner.
- Every API endpoint requires authentication again, **except**: tracking pixel,
  unsubscribe, inbound reply webhook, `/health`, `/health/ready`, and the
  Google OAuth callback.
- Every request binds the user's tenant to the DB session
  (`set_tenant_for_session`); background tasks bind the tenant of the row
  they work on.
- Remove single-workspace assumptions: `services/local_workspace.py`, the
  `LOCAL_TENANT_ID` usage in the inbox poller, onboarding and elsewhere. The
  test-only `X-Test-Auth` override is replaced by real tokens.
- **Keys:** each workspace adds provider keys (LLM providers, Serper,
  Proxycurl) under Integrations. Stored with the per-tenant vault key, never
  returned by the API, verified by a real probe on Test. Environment/.env
  provider keys become a self-hosting option `ALLOW_ENV_PROVIDER_KEYS`,
  default `false`; startup fails in production if it is `true`.
- **Mailboxes:** per-workspace SMTP + IMAP, as today.
- **Account self-service:** change password; delete account (re-auth
  required; permanently deletes the workspace and its data); export data
  (existing GDPR export).
- **Operator admin console** restored from history: users/workspaces list,
  usage, suspend/unsuspend. Admin flag set in the database only. No billing
  screens.

## 3. Usage limits, abuse controls, email compliance

Per-workspace limits (settings, changeable without code; exceeded → HTTP 429
with a clear message; shown on the dashboard):

| Limit | Default | Setting |
|---|---|---|
| Emails sent per day (all mailboxes) | 200 | `LIMIT_SENDS_PER_DAY` |
| Emails per mailbox per day | 50 (existing per-mailbox cap) | `DEFAULT_DAILY_SEND_CAP` |
| Leads scraped per month | 1,000 | `LIMIT_LEADS_PER_MONTH` |
| Concurrent scraping jobs | 2 | `LIMIT_CONCURRENT_SCRAPES` |
| Mailboxes | 3 | `LIMIT_MAILBOXES` |
| Drafts generated per hour | 100 | `LIMIT_DRAFTS_PER_HOUR` |

- Usage counting reuses the usage-event model that billing used, without plans.
- **Warm-up:** a new mailbox's effective daily cap starts at 10 and rises by
  10 per day up to its configured cap.
- **Compliance in every campaign email:** unsubscribe link (exists) plus
  RFC 8058 one-click `List-Unsubscribe` and `List-Unsubscribe-Post` headers;
  the workspace's postal address in the footer (required before the first
  campaign send); unsubscribes, hard bounces and "stop" replies added to the
  workspace suppression list automatically; repeated hard bounces pause the
  mailbox and notify the user.
- **Abuse controls:** per-IP signup rate limit; campaign sending blocked until
  the user's email is verified; operator suspend stops a workspace's sending
  and scraping immediately; Terms of Service and Acceptable Use pages
  (owner-approved wording).
- Scraping rate-limited per workspace per source, on its own queue.

## 4. Reliability, security, known bugs

Known bugs fixed before launch:
- Host allowlist automatically includes the hostname of `PUBLIC_BASE_URL`;
  production startup fails if it is not allowed.
- Scrape task gets its own time limits above the scrape budget; on
  `SoftTimeLimitExceeded` the job is marked failed. The inbox-poll guard
  re-raises `SoftTimeLimitExceeded` instead of counting it as a mailbox error.
- Follow-up sends pass `In-Reply-To`/`References` of the previous send so they
  thread.
- Missing-key (428) message points to Integrations (correct again).

Build and deploy:
- `Dockerfile.api` installs dependencies before copying source.
- Python dependencies locked (lock file) for reproducible builds.
- All container images pinned.
- CI: MinIO image from `quay.io` (Docker Hub no longer serves it).

No double sends / no lost jobs:
- Celery `acks_late=True` with a visibility timeout longer than the longest
  task, so a crashed worker's job is redelivered.
- Sends are idempotent: a step is claimed (row lock, status `sending`) before
  the SMTP call; a redelivered task skips steps already `sending`/`sent`.

Security:
- CORS allows only the web origin; Host allowlist; security headers; HTTPS.
- Secrets live in Render/Vercel encrypted environment settings, never in git.
- Owner rotates the Groq key that was pasted into chat.

Observability:
- Sentry (API, workers, web); structured logs with request IDs; uptime check on
  `/health/ready`; alert on Celery queue depth; tested database restore.

## 5. Testing and launch verification

- CI on every push: full API suite, ruff, mypy, web lint/typecheck/build.
- Restored auth tests (signup, login, refresh, reset, verify, Google) and
  cross-tenant isolation tests, including fanned-out background tasks.
- New tests: usage limits (429), warm-up, `List-Unsubscribe` headers and
  postal-address footer, idempotent send under task redelivery, scrape
  time-limit handling, Host allowlist includes the public host,
  `ALLOW_ENV_PROVIDER_KEYS` forced off in production.
- Live-model tests remain gated on test keys.
- Launch check on a staging copy, with two real test accounts: email signup +
  verify; Google sign-in; each adds its own Groq key and a real test mailbox;
  import leads → draft → send → reply captured; unsubscribe → suppression;
  account B cannot see anything of account A's; a usage limit triggers;
  account deletion.
- Load test: ~200 simulated API users plus many concurrent mailbox polls.

## Rollout

1. **Phase 1 — Code:** sections 2–4, task by task with reviews, on branch
   `public-multi-user`.
2. **Phase 2 — Infrastructure:** Render (API, workers, beat, Postgres, Redis),
   Vercel (web), R2, Resend, Sentry, domain + DNS. RLS feasibility check first.
3. **Phase 3 — Launch:** staging → launch checklist → production on the
   owner's domain.

## Inputs needed from the owner (phase 2; secrets entered by the owner in the Render/Vercel dashboards, never in chat)

- Render, Vercel and Cloudflare accounts (the Vercel connector here needs authorizing in claude.ai connector settings).
- A domain and access to its DNS.
- A Resend account with the sending domain verified.
- A Google OAuth app (client ID and secret) with the redirect URIs this build specifies.
- A Sentry account (free tier works).
- Terms of Service / Acceptable Use wording, or approval to start from a template.

## Out of scope (this launch)

- Stripe billing and paid plans (later phase; limits are built so plans can plug in).
- Microsoft sign-in.
- CRM (Google Sheets) sync and calendar provider clients (remain stubs, CRM hidden from navigation).
- Team seats / multiple users per workspace (one owner per workspace at launch).
