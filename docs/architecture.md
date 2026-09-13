# Architecture

Summary of the layer choices and the invariants the test suite enforces.

## Stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI (async) | Typed, OpenAPI-native, async-first. |
| ORM | SQLAlchemy 2.0 async | RLS-friendly with raw `set_config` calls. |
| Migrations | Alembic | Standard. |
| DB | PostgreSQL 16 + RLS | Tenant isolation enforced at the DB layer, not just the app. |
| Cache / queue | Redis 7 | Celery broker + result backend. |
| Worker | Celery 5 (`worker` + `beat`) | Battle-tested for long-running and scheduled tasks. |
| LLM | LiteLLM, 13 providers | Single API surface, multi-provider, keys from `.env`. |
| Frontend | Next.js 14 App Router | SSR, file-based routing, RSC-ready. |
| UI | Tailwind + shadcn-style components | Don't reinvent components. |
| Server state | TanStack Query v5 | Caching, mutations, optimistic updates. |
| Forms | react-hook-form + zod | Validation matches our Pydantic schemas. |
| Secrets | Per-workspace Fernet DEK from a master KEK (`VAULT_MASTER_KEY`) | Wraps mailbox passwords and any provider key stored via the app. |
| Object storage | S3-compatible (MinIO) | Draft bodies, exports, attachments. |
| Email out | The mailbox's own SMTP credentials | Never a shared platform mailer or the operator's own IPs. |
| Email in | IMAP polling of the mailbox's inbox, plus an inbound webhook | Two independent paths to the same `ReplyService.ingest`. |

## Tenancy: one local workspace, RLS still enforced

Outreach OS is single-user: there is no signup, login, or per-request
identity. `POST`/`GET` calls carry no `Authorization` header at all. Every
request is treated as the one built-in **local workspace**, created
idempotently on first use with fixed identifiers
(`LOCAL_TENANT_ID = 00000000-0000-4000-8000-000000000001`, tenant slug
`local`, name `My Workspace`; see `services/local_workspace.py`).

The database layer did not get simpler, though — every tenant-scoped table
still has a `tenant_id` column, and Postgres Row-Level Security policies
still filter on `current_setting('app.current_tenant', true)`. The FastAPI
dependency chain (`api/deps.py`) works like this on every business
endpoint:

1. `get_current_user` returns the local workspace's `AuthContext`
   (`user_id`, `tenant_id`, `role="owner"`) — no token to decode, since
   there is exactly one workspace.
2. `get_scoped_db` opens a transaction and calls
   `set_config('app.current_tenant', '<local_tenant_id>', true)`, scoped to
   that transaction.
3. RLS then enforces the boundary the same way it always did — a query that
   forgets a `WHERE tenant_id = ...` still can't see rows outside the bound
   tenant.

Keeping RLS bound (rather than deleting it, now that there is only one
tenant) means the multi-tenant safety net stays exercised: `tests/
test_tenancy_isolation.py` still runs, via a test-only auth override that
lets tests bind two different tenant ids in the same process. The app
connects as the non-superuser `outreach` role specifically so RLS cannot be
silently bypassed (see [docs/runbook.md](runbook.md#database-roles)).

The public endpoints (tracking pixel, unsubscribe, the inbound webhook, and
the notifications WebSocket) still work without any workspace context, same
as before.

Auth, team users, admin and billing routes (`/v1/auth/*`, `/v1/users`,
`/v1/admin/*`, `/v1/billing/*`) are removed outright rather than stubbed.
Their database tables (`plan`, `subscription`, `usage_event`,
`billing_portal_token`) are left in place, unread, rather than dropped —
see [Out of scope](#out-of-scope) below.

## Sending and reply-polling flow

```text
Sequence started (POST /v1/sequences)
        │
        ▼
SequenceStep rows materialized, one per (lead, campaign step),
scheduled_at computed from step.delay_days
        │
        ▼  beat: send_due, every SEND_DUE_INTERVAL_SECONDS (default 60s)
SendService.execute_due
        │  finds due steps, picks the workspace's first active mailbox,
        │  checks the mailbox's daily_send_cap, ensures a Draft exists
        │  (generating one via the LLM if needed)
        ▼
mailer_for_mailbox(mailbox)  — builds an SmtpMailer from the mailbox's own
        │                      decrypted SMTP settings (never a shared/
        │                      platform mailer)
        ▼
Send row persisted (status queued → sent/failed), Message-ID recorded
        │
        ▼  the recipient's mail server, then eventually a reply
        │
        ▼  beat: poll_inboxes, every INBOX_POLL_INTERVAL_SECONDS (default 120s)
IMAP poll of every mailbox with imap_host set
        │  fetches unseen messages with PEEK (not yet marked \Seen),
        │  matches In-Reply-To/References to a Send row
        ▼
ReplyService.ingest — persists the Reply, classifies it, marks the source
        │              message \Seen only after it's durably handled
        ▼
GET /v1/replies, and a notification if configured
```

The inbound webhook (`POST /webhooks/inbound-email`, HMAC-signed) reaches
`ReplyService.ingest` the same way, for providers that push replies instead
of a mailbox to poll.

## The audit invariant

Every state-changing endpoint writes one row to `audit_event`. The table has
`BEFORE UPDATE` and `BEFORE DELETE` triggers that raise `audit_event is
append-only`. Each row stores `prev_hash` and `row_hash = SHA256(payload ||
prev_hash)`, so a tamper is detectable by re-walking the chain.

## Out of scope

Documented as known limitations rather than fixed in this build:

- The CRM (Google Sheets) sync and calendar provider clients remain stubs;
  the CRM sync page is removed from the web app's navigation.
- Now-unused database tables (`plan`, `subscription`, `usage_event`,
  `billing_portal_token`) are left in place rather than dropped by a
  migration. Nothing reads them.
