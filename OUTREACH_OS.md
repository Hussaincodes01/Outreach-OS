# Outreach OS

**Outreach OS** is a multi-tenant SaaS platform that automates outbound B2B sales outreach — from lead generation and research to personalized email drafting, sending, and follow-up. Built for sales teams who want AI-powered pipeline without sharing a database with competitors.

## Core Capabilities

### Lead Scraping & Enrichment
- **Multi-source scraping**: Serper (web search), company site crawling, LinkedIn (via Proxycurl)
- **Configurable ICPs** (Ideal Customer Profiles) per tenant — scrape targets matching predefined personas
- **Deduplication**: automatic merge/block logic prevents duplicate leads
- **Per-source rate limits** enforced via Redis

### BYOK AI Layer
- **13 providers**: OpenAI, Anthropic, Gemini, Groq, Mistral, DeepSeek, xAI, Cohere, Together AI, Fireworks AI, OpenRouter, Perplexity, Ollama (self-hosted)
- **Per-tenant keys only**: resolved from the encrypted vault and passed explicitly to LiteLLM. Never read from the process environment, which would leak between tenants in a shared worker
- **No silent fallback**: a missing key returns `428` with an actionable message instead of producing fabricated output
- **Live key verification**: the Test action makes a real 1-token call, so a bad key surfaces at setup rather than mid-campaign
- **Independent chat and embedding models**: draft on a provider with no embeddings API and still use the knowledge base

### AI Draft Pipeline
- **Tool-calling research agent**: the model chooses among lead profile, company site, knowledge base, previous touches, and web search, bounded by a step cap and a cumulative token budget
- **Graceful degradation**: models without function calling fall back to deterministic research; a draft is always produced
- **Full audit trail**: every tool call, argument, token count, and stop reason is recorded on `agent_run.trace`
- **RAG pipeline**: uploaded content → chunk → embed → vector search → context for the draft
- **Campaign-based drafting**: multi-step sequences that copy the sender's voice from their own sample emails

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

- **Backend**: Python 3.11 + FastAPI + SQLAlchemy 2.0 async + asyncpg + Redis
- **Frontend**: Next.js 14 (App Router) + TanStack Query. No Supabase — auth is the custom JWT layer described above
- **Database**: PostgreSQL 16 + pgvector (pgvector/pgvector:0.7.4-pg16)
- **Infrastructure**: Docker Compose (Postgres, Redis 7, MinIO S3, MailHog)
- **Background tasks**: Celery + Redis broker (eager mode in tests)
- **Object storage**: MinIO (S3-compatible) per-tenant draft/attachment storage
- **Auth**: bcrypt password hashing + JWT (HS256) with key rotation
- **AI**: LiteLLM, with credentials resolved per tenant at call time

## Testing

- 210 tests passing, 1 skipped (the live-provider test needs `OUTREACH_TEST_OPENAI_KEY`)
- `ruff` and `mypy --strict` clean across the API
- RLS isolation tests verify cross-tenant data separation
- BYOK tests verify one tenant's key is invisible to another, and that the
  process environment is never used as a fallback
- Agent tests verify the step cap, the token budget, and graceful degradation
- Config tests construct `Settings` from real environment variables — the only
  way to catch env-parsing bugs that unit tests miss
- Audit append-only tests verify immutability

## Project Status

**Verified working:** the production images build; `docker-compose.prod.yml`
brings up Postgres, Redis, migrations, API, worker and beat; `/health` returns
ok; and an end-to-end HTTP smoke test covers signup under RLS, the onboarding
checklist, the provider catalogue, `428` on a missing key, encrypted credential
storage, and audit writes.

**Not yet verified:** no call has been made to a real LLM provider. The BYOK
path, the agent's tool-calling loop, and the catalogue's model IDs are all
exercised against fakes. Run `tests/test_phase3_live_llm.py` with
`OUTREACH_TEST_OPENAI_KEY` set before trusting this with real campaigns.

**Known gaps:** leads can only be created by the scraping pipeline — there is
no import endpoint yet. Billing defaults to the stub provider, and the calendar
and CRM clients are stubs.
