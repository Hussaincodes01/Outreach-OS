<div align="center">

# Outreach OS

### AI outbound sales automation, lead intelligence, and multi-tenant outreach infrastructure

**Outreach OS is a full-stack B2B sales outreach platform for lead scraping, enrichment, AI-personalized email drafting, mailbox orchestration, reply tracking, meetings, billing, audit logs, and tenant-safe SaaS operations.**

[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Web-Next.js_14-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL_16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Queue-Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io/)
[![TypeScript](https://img.shields.io/badge/Frontend-TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Python](https://img.shields.io/badge/Backend-Python_3.10-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)

</div>

---

## What Is Outreach OS?

Outreach OS is a **multi-tenant AI sales outreach operating system**. It helps teams discover leads, enrich contacts, draft personalized campaigns, send compliant outbound email, monitor replies, schedule meetings, manage billing, and audit every tenant-scoped action.

It is designed for teams building or operating:

- AI cold email platforms
- B2B lead generation SaaS products
- Sales engagement tools
- SDR automation systems
- Multi-tenant outreach infrastructure
- Secure outbound email and CRM workflow products

## Core Product Modules

| Module | What it does |
| --- | --- |
| Lead scraping | Multi-source lead discovery using search, company sites, and enrichment providers |
| ICP management | Tenant-specific ideal customer profiles and targeting rules |
| Deduplication | Lead merge/block logic to reduce duplicates across sources |
| AI drafting | RAG-powered personalized email generation with tenant token controls |
| Campaign sequences | Multi-step outbound workflows with send and follow-up states |
| Mailboxes | Gmail, Outlook, SMTP, OAuth, and encrypted credential storage patterns |
| Reply engine | Inbound reply capture, webhook validation, and follow-up triggers |
| Meetings | Availability windows, CRM sync hooks, and meeting lifecycle models |
| Billing | Plans, usage metering, Stripe-ready abstractions, and tenant limits |
| Notifications | In-app notifications, Slack webhooks, and preference controls |
| Compliance | GDPR export/erasure, suppression lists, audit logs, and RLS isolation |

## Why This Project Stands Out

- **Tenant isolation at the database layer** with PostgreSQL Row-Level Security.
- **Hash-chained append-only audit logs** for tamper-evident operational history.
- **AI pipeline architecture** for research, retrieval, personalized drafting, and follow-up.
- **Provider-ready integrations** for LLMs, email, CRM, billing, object storage, and notifications.
- **Production-minded SaaS foundation** with tests, migrations, Docker infra, and security docs.
- **Local development first** with Docker Compose for PostgreSQL, Redis, MinIO, and MailHog.

## SEO Keywords

AI sales outreach platform, B2B lead generation SaaS, cold email automation, AI email personalization, sales engagement software, outbound sales automation, FastAPI SaaS starter, Next.js SaaS dashboard, multi-tenant SaaS boilerplate, PostgreSQL RLS SaaS, GDPR-ready outreach platform, CRM sync automation, AI SDR platform.

---

## Architecture

```text
apps/web        Next.js 14 dashboard
apps/api        FastAPI application, workers, migrations, services
packages        Shared TypeScript types
infra/docker    Local and production Docker assets
docs            Architecture, deployment, testing, runbook, threat model
scripts         Developer automation and seed scripts
```

| Layer | Technology |
| --- | --- |
| Backend API | FastAPI, Pydantic, SQLAlchemy 2.0 async |
| Frontend | Next.js 14 App Router, React, Tailwind CSS |
| Database | PostgreSQL 16, pgvector, RLS policies |
| Queue/cache | Redis, Celery |
| Object storage | MinIO / S3-compatible storage |
| Email testing | MailHog in local development |
| Auth | JWT with rotation-ready key design |
| AI | LiteLLM-compatible service layer |
| Testing | Pytest, Vitest, tenancy isolation tests |
| Infrastructure | Docker Compose, production Dockerfiles, GitHub Actions |

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/Hussaincodes01/Outreach-OS.git
cd Outreach-OS
```

### 2. Create local environment

```bash
copy .env.example .env
```

Then edit `.env` with local-only values. Do not commit `.env`.

For details, read [SETUP.md](SETUP.md).

### 3. Install dependencies

```bash
npm install
cd apps/web && npm install && cd ../..
```

For the API, use your preferred Python environment:

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
cd ../..
```

### 4. Start infrastructure

```bash
npm run dev:infra
```

### 5. Run the API

```bash
npm run dev:api
```

### 6. Run the web app

```bash
npm run dev:web
```

---

## Documentation

- [SETUP.md](SETUP.md): environment variables, secrets, and local setup tutorial
- [OUTREACH_OS.md](OUTREACH_OS.md): product capabilities and build status
- [docs/architecture.md](docs/architecture.md): system architecture and invariants
- [docs/threat-model.md](docs/threat-model.md): security posture and threat model
- [docs/runbook.md](docs/runbook.md): operations and incident notes
- [01-MASTER-PLAN.md](01-MASTER-PLAN.md): long-form roadmap and implementation plan

---

## Security And Compliance

Outreach OS is built around a few hard rules:

- Never commit `.env` files or secrets.
- Tenant data must be scoped by PostgreSQL RLS.
- Audit events are append-only.
- Credentials are encrypted through the vault service.
- Suppressions and GDPR flows are first-class features.
- Tests should protect tenancy, auth, vault, audit, and billing behavior.

Before pushing code, run:

```bash
git status --short
git check-ignore .env apps/web/.env.local
rg -n --hidden -g '!node_modules' -g '!.git' -g '!.env' -g '!.env.*' -g '!*.log' -g '!*.pyc' -g '!__pycache__/**' "API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY|DATABASE_URL|BEGIN PRIVATE"
```

---

## Roadmap

- Harden production deploys and WAF rules
- Improve CRM connectors for HubSpot and Salesforce
- Add richer campaign analytics and deliverability dashboards
- Expand AI agents for research, scoring, and reply classification
- Add organization-level role management
- Add hosted billing portal polish
- Create a clean OSS release profile

---

## License

License and commercialization terms are not finalized in this repo snapshot. Review the project plan before using this code in production.

<div align="center">

**Outreach OS: the operating layer for AI-powered outbound sales.**

[Repository](https://github.com/Hussaincodes01/Outreach-OS)

</div>
