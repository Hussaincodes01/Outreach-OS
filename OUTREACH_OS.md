# Outreach OS

**Outreach OS** is a single-user, self-hosted tool that automates outbound
B2B sales outreach — from lead import/research to personalized email
drafting, sending through your own mailbox, and reply tracking. One
workspace, `docker compose up`, your own provider keys.

## Core Capabilities

### Lead Import & Scraping
- **CSV import**: bring your own list — preview the column mapping, confirm
  it, import. No scraping key required.
- **Multi-source scraping** (optional, needs keys): Serper (web search),
  company site crawling, LinkedIn (via Proxycurl)
- **Configurable ICPs** (Ideal Customer Profiles) — scrape targets matching
  a persona
- **Deduplication**: automatic merge/block logic prevents duplicate leads
- **Per-source rate limits** enforced via Redis

### AI Drafting, Powered By Your Own Key
- **13 providers**: OpenAI, Anthropic, Gemini, Groq, Mistral, DeepSeek, xAI,
  Cohere, Together AI, Fireworks AI, OpenRouter, Perplexity, Ollama
  (self-hosted)
- **Keys from `.env`**: read from the process environment / `.env` file,
  never entered through the web app. An env key always takes precedence
  over one stored via the app.
- **No silent fallback**: a missing key returns `428` with an actionable
  message instead of producing fabricated output
- **Live key verification**: the Integrations page's Test action makes a
  real 1-token call, so a bad key surfaces immediately rather than mid-campaign
- **Independent chat and embedding models**: draft on a provider with no
  embeddings API and still use the knowledge base
- **Tool-calling research agent**: the model chooses among lead profile,
  company site, knowledge base, previous touches, and web search, bounded
  by a step cap and a cumulative token budget
- **Full audit trail**: every tool call, argument, token count, and stop
  reason is recorded on `agent_run.trace`
- **RAG pipeline**: uploaded content → chunk → embed → vector search →
  context for the draft
- **Campaign-based drafting**: multi-step sequences that copy the sender's
  voice from their own sample emails

### Send & Reply Engine
- **Real sending**: sequence sends go out through the connected mailbox's
  own SMTP credentials — never a shared platform mailer
- **Mailboxes**: SMTP for sending, optional IMAP for reply capture; Gmail
  and Outlook both work via an app password (no OAuth flow)
- **Reply capture, two paths**: a beat task polls each IMAP-enabled
  mailbox's unseen messages (`In-Reply-To`/`References` matching, PEEK
  until durably handled), and an inbound webhook (HMAC-signed) for
  providers that push instead
- **Suppression list**: opt-out management

### Meeting Scheduler
- **Meeting scheduling** with availability windows and buffer times
- **CRM sync and calendar provider clients are stubs** — see Known
  Limitations below

### Security & Compliance
- **No authentication** — see [docs/threat-model.md](docs/threat-model.md)
  before exposing this beyond localhost
- **Row-Level Security** (RLS) on every workspace-scoped table, still bound
  per request to the one local workspace — FORCE RLS + NOBYPASSRLS app role
- **Tenancy isolation tests** (via a test-only auth override) validate the
  RLS mechanism itself still works, even though there's one workspace in
  production
- **Hash-chained append-only audit log** — no UPDATE/DELETE allowed, even
  by superuser
- **GDPR endpoints**: DSAR export (NDJSON stream), Right to Erasure
  (soft-delete + anonymize, 30-day grace)
- **Vault-encrypted credentials** (Fernet per-workspace key, wrapped by
  `VAULT_MASTER_KEY`) for mailbox passwords and any provider key stored via
  the app
- **Rate limiting**: per-IP for the inbound webhook
- **Security headers**: X-Frame-Options DENY, X-Content-Type-Options
  nosniff, CSP, HSTS, Permissions-Policy

## Architecture

- **Backend**: Python 3.11 + FastAPI + SQLAlchemy 2.0 async + asyncpg + Redis
- **Frontend**: Next.js 14 (App Router) + TanStack Query. No login — the app
  opens straight into the dashboard.
- **Database**: PostgreSQL 16 + pgvector (`pgvector/pgvector:0.7.4-pg16`)
- **Infrastructure**: Docker Compose — Postgres, Redis, MinIO (`quay.io/minio/*`
  images; Docker Hub no longer serves them), GreenMail (SMTP+IMAP, `--profile e2e`)
- **Background tasks**: Celery + Redis broker; `beat` schedules `send_due`
  (default every 60s) and `poll_inboxes` (default every 120s)
- **Object storage**: MinIO (S3-compatible), draft bodies and attachments
- **AI**: LiteLLM, credentials resolved from `.env` at call time

## Testing

- API test suite (`cd apps/api && .venv/Scripts/python -m pytest`) runs
  against the dev infra (`npm run dev:infra`); `ruff check .` and
  `mypy src` are clean. Auth/billing/admin/social tests were removed along
  with those routes; tenancy-isolation tests were kept via a test-only auth
  override.
- `scripts/e2e_smoke.py` (`npm run smoke`) exercises the live, fully
  containerized stack over real HTTP, SMTP and IMAP: health, the local
  workspace, onboarding, an ICP, a CSV lead import, an SMTP mailbox
  connected to GreenMail, a real SMTP send captured by GreenMail's IMAP,
  and — when a provider key is configured — a full draft → sequence →
  send → reply-capture loop.

## Project Status

**Verified working:** `docker compose up -d --build` from the repo root
brings up Postgres, Redis, MinIO, migrations, the API, worker, beat and web;
`/health` and `/health/ready` return ok; the web app serves the dashboard;
an ICP, a CSV lead import, an SMTP mailbox connection, and a real SMTP send
captured by a local IMAP server all work end to end with no provider key
configured.

**Requires a provider key to verify further:** draft generation, the
agent's tool-calling research loop, and the full send → reply-capture loop
all need an LLM key in `.env`. `scripts/e2e_smoke.py` implements those
checks and will run them automatically once a key is present; without one,
it reports them as skipped rather than fabricating a result.

**Known gaps:** the CRM (Google Sheets) sync and calendar provider clients
are stubs; the CRM sync page is unlinked from the web app's navigation.
There is no time-of-day send-window enforcement in this build.
