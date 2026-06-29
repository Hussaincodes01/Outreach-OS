# Outreach OS

**Outreach OS** is a multi-tenant SaaS platform that automates outbound B2B sales outreach — from lead generation and research to personalized email drafting, sending, and follow-up. Built for sales teams who want AI-powered pipeline without sharing a database with competitors.

## Core Capabilities

### Lead Scraping & Enrichment
- **Multi-source scraping**: Serper (web search), company site crawling, LinkedIn (via Proxycurl)
- **Configurable ICPs** (Ideal Customer Profiles) per tenant — scrape targets matching predefined personas
- **Deduplication**: automatic merge/block logic prevents duplicate leads
- **Per-source rate limits** enforced via Redis

### AI Draft Pipeline
- **RAG pipeline**: scraped content → chunk → embed → vector search → context for LLM
- **Campaign-based drafting**: multi-step sequences with customizable templates
- **Live LLM integration** (OpenAI) with per-tenant token caps, chunked output, and error recovery
- **Knowledge Base**: per-tenant documents, chunked and indexed for semantic retrieval

### Send & Reply Engine
- **Mailbox management**: per-tenant send accounts with encrypted credential storage (Fernet + vault)
- **Send pipeline**: sequence steps → drafted content → outbound send with tracking
- **Reply monitoring**: inbound webhook endpoint (HMAC-signed) that captures replies and triggers follow-up logic
- **Suppression list**: opt-out management per tenant

### Meeting Scheduler
- **CRM sync** (Stub client, extensible to Salesforce/HubSpot): pulls leads, meetings, and syncs activity back
- **Meeting scheduling** with availability windows, buffer times, and calendar provider support

### Billing & Plans
- **Tiered plans**: Starter ($29/mo), Growth ($99/mo), Scale ($299/mo)
- **Usage metering**: sends, leads scraped, LLM tokens — per-tenant monthly rollup
- **Stripe integration** (with local stub for dev) — checkout, webhook subscription creation, portal tokens
- **Plan gating**: enforcing send caps, lead caps, CRM sync, Slack notifications, team seats per plan tier

### Notifications
- **In-app notifications**: read/unread, per-tenant
- **Slack webhooks**: tenant-configurable
- **Notification preferences**: granular opt-in per channel

### Security & Compliance
- **Row-Level Security** (RLS) on every tenant-scoped table — FORCE RLS + NOBYPASSRLS app role
- **RLS tenancy isolation tests** validate cross-tenant data leaks are impossible
- **Hash-chained append-only audit log** — no UPDATE/DELETE allowed, even by superuser
- **GDPR endpoints**: DSAR export (NDJSON stream), Right to Erasure (soft-delete + anonymize, 30-day grace)
- **Vault-encrypted credentials** (Fernet per-tenant key, wrapped by master key)
- **Rate limiting**: per-IP for auth (login=10/min, signup=5/min), per-tenant for scraping, per-IP for webhooks
- **Security headers**: X-Frame-Options DENY, X-Content-Type-Options nosniff, CSP, HSTS, Permissions-Policy
- **JWT with key rotation**: multi-secret support, kid claim, active key ID

## Architecture

- **Backend**: Python 3.10 + FastAPI + SQLAlchemy 2.0 async + asyncpg + Redis
- **Frontend**: Next.js 14 (App Router) + Supabase Client
- **Database**: PostgreSQL 16 + pgvector (pgvector/pgvector:0.7.4-pg16)
- **Infrastructure**: Docker Desktop (Postgres, Redis 7, MinIO S3, MailHog)
- **Background tasks**: Celery + Redis broker (eager mode in tests)
- **Object storage**: MinIO (S3-compatible) per-tenant draft/attachment storage
- **Auth**: bcrypt password hashing + JWT (HS256) with key rotation

## Testing

- 102 tests passing, 1 skipped (live LLM requires OPENAI_API_KEY)
- RLS isolation tests verify cross-tenant data separation
- Audit append-only tests verify immutability
- All billing, scraping, drafting, send, reply, and meeting flows tested end-to-end

## Project Status

- **Phases 0-7 complete**: multi-tenancy, scraping, drafting, send/reply, meetings, billing
- **Phase 8 (Hardening) in progress**: rate limiting, security headers, GDPR, JWT rotation, load testing (k6), WAF rules, SOC2 artifacts
- **Supabase migration path documented**: optional migration from custom auth/JWT/RLS to Supabase Auth + Realtime + Edge Functions
