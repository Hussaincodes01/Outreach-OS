# Architecture

This is a stub. For the canonical architecture and the full multi-phase roadmap,
see [`../01-MASTER-PLAN.md`](../01-MASTER-PLAN.md).

## Phase 0+1 scope (this build)

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI (async) | Typed, OpenAPI-native, async-first. |
| ORM | SQLAlchemy 2.0 async | RLS-friendly with raw `set_config` calls. |
| Migrations | Alembic | Standard. |
| DB | PostgreSQL 16 + RLS | Tenant isolation enforced at the DB layer, not just the app. |
| Cache / queue | Redis 7 | Celery broker + result backend. |
| Worker | Celery 5 | Battle-tested for long-running tasks. |
| LLM | LiteLLM (stub for now) | Single API, multi-provider, fallback. |
| Frontend | Next.js 14 App Router | SSR, file-based routing, RSC-ready. |
| UI | Tailwind + shadcn-style components | Don't reinvent components. |
| Server state | TanStack Query v5 | Caching, mutations, optimistic updates. |
| Forms | react-hook-form + zod | Validation matches our Pydantic schemas. |
| Auth | Custom JWT (Phase 0+1) — Auth.js v5 upgrade in V1 | Pragmatic to ship. |
| Secrets | Per-tenant Fernet DEK from a master KEK | v1. v2 swaps to AWS KMS envelope encryption. |
| Object storage | S3-compatible (MinIO locally) | Reports, exports, attachments. |
| Email out | Per-tenant OAuth (Gmail, Outlook) or SMTP | We never send cold mail from our own IPs. |

## The tenancy invariant

Every multi-tenant table has a `tenant_id` column. Postgres Row-Level Security
policies filter on `current_setting('app.current_tenant', true)`. The FastAPI
dependency `get_scoped_db` decodes the request's JWT, opens a transaction, and
calls `set_config('app.current_tenant', '<tid>', true)` so the setting is
transaction-scoped. RLS guarantees tenant isolation even if a developer
forgets a `WHERE tenant_id = ...` in a query.

This is enforced and tested by `tests/test_tenancy_isolation.py`. CI fails if
that test is removed or skipped.

## The audit invariant

Every state-changing endpoint writes one row to `audit_event`. The table has
`BEFORE UPDATE` and `BEFORE DELETE` triggers that raise `audit_event is
append-only`. Each row stores `prev_hash` and `row_hash = SHA256(payload ||
prev_hash)`, so a tamper is detectable by re-walking the chain.

## Open-source posture

The repository is currently proprietary. The architecture is structured so
that an OSS release (Phase 9 in the master plan) is a clean cut:

- No cloud-only dependencies in core code paths.
- BYO API keys for LLM, scraping, and transactional email.
- Single-tenant install supported by skipping the multi-tenant RLS layer
  (would require a separate `single_tenant` build profile, not yet implemented).
- All hard-to-replicate business logic (scoring, niche detection, tone
  analysis) lives behind stable interfaces so it can be re-implemented
  by an OSS maintainer without touching the SaaS moat.
