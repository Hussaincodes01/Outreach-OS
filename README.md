<div align="center">

# Outreach OS

### A single-user AI outbound sales tool you run yourself

**Outreach OS is a self-hosted outbound sales tool: lead import/scraping, AI-personalized email drafting, mailbox sending over SMTP, reply tracking over IMAP, and campaign sequencing — one Docker Compose command, one workspace, your own provider keys.**

[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Web-Next.js_14-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL_16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Queue-Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io/)
[![TypeScript](https://img.shields.io/badge/Frontend-TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Python](https://img.shields.io/badge/Backend-Python_3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)

</div>

---

## What Is Outreach OS?

Outreach OS is a **single-user outbound sales tool you run on your own machine or server**. There is no signup, no login, and no shared account — `docker compose up` brings up one workspace that is yours alone, and it opens straight into the dashboard. It helps you import or discover leads, draft personalized outbound campaigns with your own AI provider key, send through your own mailbox, and track replies.

It is built for:

- Founders and small teams doing their own outbound
- Anyone who wants an AI drafting/sending tool without handing a vendor their contact list or API keys
- Self-hosting on a laptop, a home server, or a small VPS

## Core Product Modules

| Module | What it does |
| --- | --- |
| AI drafting | Your own provider key drives RAG-powered, personalized email generation |
| Agentic research | A tool-calling agent decides what to look up per lead, within a hard step and token budget |
| Lead import | Import your own list from CSV, or discover leads via search/enrichment providers |
| ICP management | Ideal customer profiles and targeting rules for scraping |
| Deduplication | Lead merge/block logic to reduce duplicates across sources |
| Campaign sequences | Multi-step outbound workflows with send and follow-up states |
| Mailboxes | Connect any SMTP/IMAP mailbox — Gmail and Outlook via an app password |
| Reply engine | IMAP polling and an inbound webhook, both matching replies to the original send |
| Meetings | Availability windows and meeting lifecycle models (calendar sync is a stub — see Known Limitations) |
| Notifications | In-app notifications and Slack webhooks |
| Compliance | GDPR data export, suppression lists, and audit logs (wipe all data with `docker compose down -v`) |

## API Keys In `.env`

Outreach OS never asks you to paste a key into the UI. Every provider key is
read from environment variables — the `.env` file at the repo root, filled in
after `npm run setup` creates it.

- **Naming rule:** `<PROVIDER>_API_KEY` (and `<PROVIDER>_API_BASE` for
  gateway/self-hosted providers), where `<PROVIDER>` is the provider id
  upper-cased with every non-alphanumeric character replaced by `_` — e.g.
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `TOGETHER_AI_API_KEY`.
- **What each feature needs:**
  - An LLM provider key (OpenAI, Anthropic, Gemini, Groq, Mistral, DeepSeek,
    xAI, Cohere, Together AI, Fireworks AI, OpenRouter, Perplexity, or a
    self-hosted Ollama) for draft generation and reply classification.
  - `SERPER_API_KEY` for web-search-based lead scraping.
  - `PROXYCURL_API_KEY` for LinkedIn profile enrichment.
  - (`RAPIDAPI_API_KEY`, `SCRAPINGBEE_API_KEY` cover other optional scraping
    sources.)
- **Precedence:** an environment/`.env` key always wins over anything stored
  through the app.
- Without any LLM key set, the app still runs — draft generation just
  returns an actionable `428` instead of fabricating output. The
  **Integrations** page shows which providers are configured (from `.env`)
  and lets you fire a real test call; it does not collect keys.

## Why This Project Stands Out

- **Keys stay yours** — read straight from `.env`, never stored in a shared
  server-side account.
- **Real sending, real receiving** — campaign sends go out through your own
  mailbox's SMTP credentials; replies are captured either by polling that
  mailbox's IMAP inbox or via an inbound webhook.
- **Agentic research with hard cost limits** — the model picks its tools,
  bounded by step count and token budget.
- **Hash-chained append-only audit log** for tamper-evident operational
  history, even with a single user.
- **Self-serve onboarding** derived from live workspace state, so the
  checklist can't go stale.
- **One command to run it all** — `npm start` brings up Postgres, Redis,
  MinIO, the API, worker, beat and the web app.

## Mailboxes

Outreach OS connects mailboxes over **SMTP for sending** and, optionally,
**IMAP for reply capture** — no OAuth flow, no Google/Microsoft app
verification to wait on. Gmail and Outlook both work fine over SMTP/IMAP
using an **app password**:

- Gmail: enable 2-Step Verification, then create an
  [App Password](https://myaccount.google.com/apppasswords); use
  `smtp.gmail.com:587` and `imap.gmail.com:993`.
- Outlook/Microsoft 365: create an app password under Security settings; use
  `smtp.office365.com:587` and `outlook.office365.com:993`.

A mailbox with only SMTP settings is send-only. Add the IMAP fields and the
`poll_inboxes` background task picks up replies automatically, matching them
to the original send by `In-Reply-To`/`References`.

---

## Architecture

```text
apps/web        Next.js 14 dashboard
apps/api        FastAPI application, workers, migrations, services
packages        Shared TypeScript types
infra/docker    Docker Compose and Dockerfiles
docs            Architecture, deployment, testing, runbook, threat model
scripts         Setup, the e2e smoke test, and other automation
```

| Layer | Technology |
| --- | --- |
| Backend API | FastAPI, Pydantic, SQLAlchemy 2.0 async |
| Frontend | Next.js 14 App Router, React, Tailwind CSS |
| Database | PostgreSQL 16, pgvector, RLS policies (bound to one local workspace) |
| Queue/cache | Redis, Celery (worker + beat) |
| Object storage | MinIO / S3-compatible storage |
| Email | SMTP for sending, IMAP polling + an inbound webhook for replies; GreenMail in local/e2e testing |
| AI | LiteLLM across 13 providers, keys read from `.env` |
| Agent | LangGraph pipeline with a tool-calling research loop |
| Testing | Pytest, tenancy isolation tests (test-only auth override), agent-budget tests |
| Infrastructure | Docker Compose, one Dockerfile per service, GitHub Actions |

---

## Quick Start

```bash
git clone https://github.com/Hussaincodes01/Outreach-OS.git
cd Outreach-OS
npm run setup      # creates .env, fills VAULT_MASTER_KEY / INBOUND_WEBHOOK_SECRET
```

Open `.env` and add your provider key(s) — see [API Keys In `.env`](#api-keys-in-env)
above. This step is optional; the app runs without a key, drafting just
returns `428` until one is set.

```bash
npm start           # docker compose up -d --build
```

Then open [http://localhost:3000](http://localhost:3000). Stop the stack
with `npm stop`; follow logs with `npm run logs`.

For a from-scratch walkthrough (dev infra, running the API/web natively,
tests), read [SETUP.md](SETUP.md).

### Verify it end to end

```bash
npm run smoke        # scripts/e2e_smoke.py — real HTTP, SMTP and IMAP against the live stack
```

Requires the stack running with the `e2e` profile
(`docker compose --profile e2e up -d --build`), which also starts GreenMail,
a local SMTP+IMAP test server. See [docs/runbook.md](docs/runbook.md) for
what each check proves.

Run it **once with a real LLM provider key in `.env`** (then
`docker compose restart api worker beat`). Without a key the draft checks
report `SKIP`, because the API answers `428` rather than fabricating output;
with a key the script exercises the whole live loop: AI draft, real SMTP send,
and the reply captured over IMAP.

---

## Documentation

- [SETUP.md](SETUP.md): environment variables, secrets, and local setup tutorial
- [OUTREACH_OS.md](OUTREACH_OS.md): product capabilities and build status
- [docs/architecture.md](docs/architecture.md): system architecture and invariants
- [docs/threat-model.md](docs/threat-model.md): security posture and threat model
- [docs/runbook.md](docs/runbook.md): operations and incident notes

---

## Security And Compliance

Outreach OS is built around a few hard rules:

- Never commit `.env` files or secrets.
- There is no authentication. Do not expose the stack to the internet
  without an authenticating reverse proxy in front of it — see
  [docs/threat-model.md](docs/threat-model.md).
- RLS still scopes every query to the local workspace, and audit events are
  append-only.
- Credentials (mailbox SMTP/IMAP passwords, any stored provider key) are
  encrypted through the vault service.
- Suppressions and GDPR flows are first-class features.

Before pushing code, run:

```bash
git status --short
git check-ignore .env apps/web/.env.local
rg -n --hidden -g '!node_modules' -g '!.git' -g '!.env' -g '!.env.*' -g '!*.log' -g '!*.pyc' -g '!__pycache__/**' "API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY|DATABASE_URL|BEGIN PRIVATE"
```

---

## Roadmap

- Verify the agent's tool-calling loop against every supported provider
- Improve CRM connectors for HubSpot and Salesforce (Google Sheets sync is
  currently a stub — see [OUTREACH_OS.md](OUTREACH_OS.md))
- Add richer campaign analytics and deliverability dashboards
- Replace the stub calendar/CRM clients with real integrations
- An authenticating reverse-proxy recipe for exposing the stack safely

---

## License

License and commercialization terms are not finalized in this repo snapshot. Review the project plan before using this code in production.

<div align="center">

**Outreach OS: run your own AI outbound sales tool.**

[Repository](https://github.com/Hussaincodes01/Outreach-OS)

</div>
