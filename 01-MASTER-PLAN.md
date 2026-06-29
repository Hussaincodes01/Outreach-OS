# Project Plan — AI Sales Outreach SaaS (working name: **Outreach OS**)

> Combining `Scrapling` (adaptive web scraping) + `sales-outreach-automation-langgraph` (LangGraph agents) into a deployable, licensed, multi-tenant SaaS for cold outreach.
> Assumed team: **solo / small team**. Assumed MVP horizon: **4–6 months part-time, ~3 months full-time**.

---

## 0. Reality Checks Before You Read Further

Read these. They will save you weeks.

1. **No software is uncrackable.** What we can do is make cracking more expensive than buying. We do that by keeping the valuable logic on **our** server (cloud SaaS) and only shipping a thin client. For the optional self-hosted enterprise tier, we use signed Ed25519 licences + online activation + obfuscated bytecode. That's the realistic ceiling.
2. **Email deliverability is the hardest engineering problem in this product, not the AI.** The agent that writes pretty emails is the easy 30%. The infra to actually deliver them at scale without getting blacklisted is the hard 70%. See `04-EMAIL-DELIVERABILITY-OPTIONS.md`.
3. **LinkedIn does not allow scraping.** Doing it directly from your servers — or from your customers' sessions — is a ToS violation, gets accounts banned, and is the #1 way you'll get sued. We use third-party LinkedIn data resellers (RapidAPI, Proxycurl, Apollo) who shoulder that liability.
4. **Multi-tenant isolation is non-negotiable.** Customer A must never see Customer B's leads, emails, or credentials. We design for this from day one because retrofitting it is a nightmare.
5. **You will not finish the original feature list in v1.** The list below is the *eventual* product. The MVP is a strict subset. I mark MVP scope explicitly.

---

## 1. What We're Building (One Paragraph)

A cloud-hosted SaaS that lets a sales team upload an Ideal Customer Profile (ICP), then has AI agents (a) scrape leads matching that ICP from public sources, (b) research each lead deeply, (c) qualify them, (d) draft personalised outreach in the customer's voice, (e) send through the customer's connected mailbox with throttling and warmup awareness, (f) handle follow-ups on a schedule, (g) detect replies and book meetings via the customer's connected calendar, and (h) audit every action in an immutable log. Companies buy a licence (subscription) and log in via the web. An optional self-hosted tier with signed licence keys is available for enterprise.

---

## 2. The Stack

I'm picking *boring, mature* tech. We are not here to win architecture awards.

### Backend
| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | Both source repos are Python. LangGraph is Python-first. |
| API framework | **FastAPI** | Async, typed, excellent OpenAPI docs. |
| Async tasks | **Celery + Redis** | Battle-tested. Scraping/LLM calls are long-running. |
| Agent orchestration | **LangGraph** (kept from kaymen99) | Already proven for this exact workflow. |
| Scraping | **Scrapling** (kept) | BSD-3 licensed, has adaptive parsing + stealth fetchers + an MCP server. |
| LLM abstraction | **LiteLLM** | One API, swap between Claude / Gemini / OpenAI. Multi-provider fallback you asked for. |
| Database | **Postgres 15+** with **Row-Level Security** | RLS is how we enforce tenant isolation at the DB layer, not just the app layer. |
| ORM | **SQLAlchemy 2.0 + Alembic** | Standard. |
| Vector store | **pgvector** (Postgres extension) | Don't add a separate vector DB until you need to. RAG for case studies fits in pgvector fine. |
| Cache + queue broker | **Redis 7+** | Dual purpose. |
| Object storage | **S3-compatible** (Cloudflare R2 or AWS S3) | For generated reports, attachments, exports. |
| Secrets | **Hashicorp Vault** OR **AWS KMS + Secrets Manager** | Customer mailbox tokens / API keys must be encrypted at rest with a per-tenant key. |

### Frontend
| Layer | Choice | Why |
|---|---|---|
| Framework | **Next.js 14+ (App Router)** | SSR, great DX, handles auth flows cleanly. |
| Language | **TypeScript** | Non-negotiable on a serious project. |
| UI lib | **shadcn/ui + Tailwind** | Don't reinvent components. |
| State | **TanStack Query** + **Zustand** | Server state vs client state separated. |
| Forms | **react-hook-form + zod** | Validation that matches your backend Pydantic models. |
| Charts | **Recharts** | For the analytics dashboard. |
| Auth | **NextAuth (Auth.js)** with our backend as provider | Centralises OAuth flows for Gmail/Outlook/etc. |

### Infra & Ops
| Layer | Choice | Why |
|---|---|---|
| Container runtime | **Docker** + **Docker Compose** for dev | Keeps Scrapling's browser deps contained. |
| Orchestration (cloud) | Start with **Fly.io** or **Railway** → graduate to **Kubernetes (EKS/GKE)** when revenue justifies | Don't K8s on day one. |
| CI/CD | **GitHub Actions** | Free tier is plenty. |
| Monitoring | **Sentry** (errors) + **Grafana Cloud** or **Better Stack** (logs/metrics) | |
| Email sending | **Customer-connected mailboxes** via Gmail/Microsoft Graph OAuth (default) + optional SMTP | See dedicated doc. We do NOT send from our own IPs for cold outreach. |
| Payments | **Stripe Billing** (cloud SaaS) + custom licence-key issuer (self-hosted tier) | Stripe handles subscriptions, invoicing, tax. |

### What we deliberately are NOT using
- **No microservices in v1.** Monolith first. Split later when you have a reason. Premature splitting kills small teams.
- **No Kubernetes in v1.** Fly.io / Railway scale to surprising sizes.
- **No separate vector DB** (Pinecone, Weaviate). pgvector is fine until you have >10M embeddings.
- **No GraphQL.** REST + OpenAPI is simpler and the autogenerated client is great.
- **No custom auth.** Use Auth.js / Authentik / a managed identity provider. Auth bugs are how startups get owned.

---

## 3. High-Level Architecture

```
                  ┌─────────────────────────────────┐
                  │   Next.js Frontend (web app)    │
                  │  - Tenant dashboard             │
                  │  - Credential / API key vault   │
                  │  - Campaign builder             │
                  │  - Audit log viewer             │
                  └────────────┬────────────────────┘
                               │ HTTPS + Bearer JWT
                  ┌────────────▼────────────────────┐
                  │       FastAPI Gateway           │
                  │  - Auth middleware              │
                  │  - Tenant resolver              │
                  │  - Licence validator            │
                  │  - Rate limiter (per-tenant)    │
                  └────┬──────────────────┬─────────┘
                       │                  │
        ┌──────────────▼──────┐   ┌───────▼────────────┐
        │   Sync API services │   │   Celery workers   │
        │  - Tenants          │   │   (long-running)   │
        │  - Campaigns        │   │  - Scraping jobs   │
        │  - Leads            │   │  - LangGraph runs  │
        │  - Mailboxes        │   │  - Email sender    │
        │  - Audit log read   │   │  - Follow-up cron  │
        └────────┬────────────┘   └────────┬───────────┘
                 │                         │
                 │     ┌───────────────────┼─────────────────┐
                 │     │                   │                 │
        ┌────────▼─────▼──┐    ┌───────────▼──────┐  ┌───────▼──────┐
        │  Postgres (RLS) │    │   Redis (broker  │  │  S3 / R2     │
        │  - tenants      │    │   + cache)       │  │  - reports   │
        │  - users        │    └──────────────────┘  │  - exports   │
        │  - leads        │                          └──────────────┘
        │  - campaigns    │
        │  - email_events │
        │  - audit_log    │
        │  - secrets_kms  │
        │  - embeddings   │
        └─────────────────┘
                 │
        ┌────────▼─────────────────────────────────────────────────┐
        │                External Integrations                     │
        │  LiteLLM → Claude / Gemini / OpenAI                      │
        │  Scrapling → arbitrary websites                          │
        │  Proxycurl/RapidAPI → LinkedIn data (NEVER direct)       │
        │  Serper/Brave → web search                               │
        │  Gmail/Microsoft Graph (per-tenant OAuth) → send mail    │
        │  Google/Outlook Calendar (per-tenant OAuth) → schedule   │
        │  HubSpot / Salesforce / Airtable (optional CRMs)         │
        │  Stripe → billing                                        │
        └──────────────────────────────────────────────────────────┘
```

### The Multi-Tenancy Model

Every Postgres table that holds customer data has a `tenant_id` column. We enable Postgres **Row-Level Security** so even a SQL injection on one tenant cannot leak another tenant's rows. The FastAPI middleware sets `SET LOCAL app.current_tenant = '<uuid>'` at the start of every request transaction. RLS policies filter on that. This is how Linear, Supabase, etc. do it.

---

## 4. The Combined Agent Flow (Scrapling + LangGraph fusion)

The original kaymen99 flow assumed leads already exist in a CRM. We extend it: leads are **also discoverable** via Scrapling.

```
┌──────────────────┐
│  ICP Definition  │  (industry, size, geo, signals — set per campaign)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  LEAD DISCOVERY  │  ← Scrapling
│  (new node)      │     - Search engines (Serper)
│                  │     - Industry directories
│                  │     - Job boards (signal: hiring = budget)
│                  │     - Tech-stack databases (BuiltWith, Wappalyzer)
│                  │     - Customer's own CRM (HubSpot/Airtable/Sheets)
└────────┬─────────┘
         │ raw lead candidates
         ▼
┌──────────────────┐
│  ENRICHMENT      │  ← Scrapling + Proxycurl/RapidAPI
│                  │     - Company website (about, blog, careers)
│                  │     - LinkedIn (via reseller, NEVER direct)
│                  │     - Recent news (Serper)
│                  │     - Social signals
│                  │     - Funding / hiring data
└────────┬─────────┘
         │ enriched lead profile
         ▼
┌──────────────────┐
│  NICHE DETECTION │  ← LLM
│  (new node)      │     "What industry/sub-niche is this lead in?
│                  │      What's their tone? Formal/casual/technical?
│                  │      What signals reveal current pain?"
└────────┬─────────┘
         │ niche tags + tone profile
         ▼
┌──────────────────┐
│  QUALIFICATION   │  ← LLM
│                  │     Score against ICP. Below threshold → reject + log.
└────────┬─────────┘
         │ qualified lead
         ▼
┌──────────────────┐
│  RAG: CASE       │  ← pgvector
│  STUDY MATCH     │     Pull customer's most relevant past wins for this niche.
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  PERSONALISATION │  ← LLM (with niche-specific prompt template)
│                  │     - Custom outreach report (Google Doc / PDF)
│                  │     - Email draft (matched to lead's tone)
│                  │     - Subject line A/B variants
│                  │     - Interview/call script
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  HUMAN REVIEW    │  ← optional, configurable per-campaign
│  GATE            │     "Auto-send" vs "Review queue".
│                  │     For MVP, default = review queue.
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  SEND ENGINE     │  ← Gmail / Graph API per-tenant OAuth
│                  │     - Throttle to safe daily limits
│                  │     - Random jitter
│                  │     - Track opens/clicks (with privacy notice)
│                  │     - Log to audit
└────────┬─────────┘
         │ message_id
         ▼
┌──────────────────┐
│  REPLY DETECTION │  ← Inbox watcher (IMAP IDLE / Gmail Pub/Sub)
│                  │     - Classify: positive / negative / OOO / question
│                  │     - Stop sequence on positive/negative
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  FOLLOW-UP       │  ← Celery beat scheduler
│  ENGINE          │     Days 3, 7, 14, 21 (configurable cadence).
│                  │     Each follow-up regenerated with fresh context.
└────────┬─────────┘
         │ on positive reply
         ▼
┌──────────────────┐
│  MEETING BOOKER  │  ← Calendar OAuth + scheduling LLM
│                  │     Reads available slots, proposes 3, sends ICS,
│                  │     creates event on confirm.
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  CRM SYNC +      │  ← all events
│  AUDIT WRITE     │     Status updates pushed back to customer's CRM.
└──────────────────┘
```

Every node writes a structured event to the audit log. That's how you get the "audit everything" requirement.

---

## 5. The Audit Log

This is too important to bury. Spec:

- One `audit_event` row per significant action.
- Append-only (no UPDATE, no DELETE) — enforced by Postgres role permissions.
- Cryptographic chaining: each row stores `prev_hash = SHA256(prev_row_serialised)` so tampering is detectable.
- Schema:
  ```
  id              UUID PK
  tenant_id       UUID NOT NULL
  actor           ENUM(user, system, agent)
  actor_id        UUID
  action          TEXT  -- e.g. "lead.scraped", "email.sent", "meeting.booked"
  target_type     TEXT
  target_id       UUID
  payload         JSONB  -- redacted view of relevant data
  ip_address      INET
  user_agent      TEXT
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  prev_hash       BYTEA
  row_hash        BYTEA  -- SHA256 of all above fields
  ```
- A daily background job exports yesterday's events to S3 with the final hash anchored to a public timestamping service (optional, enterprise). This is what gives you a defensible "we didn't tamper with the records" story.
- The dashboard has a filterable, exportable audit log view per tenant. Users can also export their own audit data (GDPR).

---

## 6. Licence-Key & Anti-Piracy Design (for Cloud + Self-Hosted)

### Cloud SaaS (the default)
You don't need a licence-key system. You need **subscription state**. Stripe Billing tells your backend whether tenant X is `active`, `past_due`, or `cancelled`. The backend gates feature access on that. This is fine and standard.

### Self-Hosted Enterprise Tier
This is where licence keys matter.

- **Licence format**: a signed JWT (`alg: EdDSA / Ed25519`). Payload contains `customer_id`, `seats`, `features[]`, `issued_at`, `valid_until`, `hardware_fingerprint_hash` (optional).
- **Issuer**: a tiny internal admin tool you run. Holds the private key. The customer never sees it.
- **Verifier**: every self-hosted instance ships with the **public key only**. On startup it validates the licence JWT signature offline.
- **Online activation**: on first boot the instance phones home to register itself, gets a node ID, and fetches the latest licence revocation list. Daily heartbeat thereafter. If the heartbeat fails for >7 days, the instance enters read-only mode.
- **Tamper resistance**: the Python source is compiled to native via **Cython** or packaged with **Nuitka** for self-hosted. This is not "uncrackable" — it just raises the cost of cracking above the licence price. A determined attacker still wins. That's fine; they're not your customer.
- **What's checked at runtime**:
  - Licence JWT signature
  - `valid_until` not expired
  - Active feature flags match the request
  - Heartbeat freshness
  - (optional) Hardware fingerprint matches issued one
- **Revocation**: maintain a CRL (certificate revocation list) at a known URL. Self-hosted instances pull it on heartbeat. Issuing a refund / stopping a thief = adding their licence ID to the CRL.

> **Be honest with yourself**: any customer technical enough to run a self-hosted server is also technical enough to crack the binary if they really want to. The licence system protects you from casual piracy and gives you legal standing in commercial disputes. That's its real job. Don't pretend otherwise.

---

## 7. Phase-Wise Roadmap

I'm separating **MVP (must ship)** from **V1 (paying customers)** from **V2 (enterprise)**. Don't skip ahead.

### Phase 0 — Foundations (Week 1–2)
- [ ] Set up monorepo (`apps/web`, `apps/api`, `packages/shared`, `infra/`).
- [ ] Postgres + Redis + S3 in Docker Compose for local dev.
- [ ] CI pipeline (lint, type-check, test) on GitHub Actions.
- [ ] Sentry hooks in both apps.
- [ ] Auth scaffold (Auth.js → FastAPI session/JWT).
- [ ] Tenant + User + RLS policies. **Test with two seeded tenants that you can verify cannot see each other's data.**
- [ ] Empty admin UI shell with sidebar nav.
- [ ] Deploy a hello-world to Fly.io / Railway end-to-end.

**Exit criterion**: you can sign up, log in, and the database isolates tenants. Nothing else.

### Phase 1 — Credential Vault & Mailbox Connection (Week 3–4)
- [ ] Encrypted credential storage (per-tenant DEK wrapped by master KEK).
- [ ] UI: "Integrations" page where customer adds API keys (LLM provider keys, Serper, Proxycurl, etc.) — these are stored encrypted, never exposed to frontend after save.
- [ ] Gmail OAuth flow → store refresh token encrypted.
- [ ] Microsoft Graph OAuth flow → same.
- [ ] SMTP credential form (encrypted) for customers using non-Google/MS mail.
- [ ] Calendar OAuth flow (same providers).
- [ ] "Test connection" button per integration.

**Exit criterion**: customer can connect their Gmail and we can send a test email through it.

### Phase 2 — Lead Scraping (Scrapling integration) (Week 5–6)
- [ ] Vendor `Scrapling` as a library. Wrap each fetcher (Fetcher, StealthyFetcher, DynamicFetcher) behind our internal `ScrapingService`.
- [ ] Implement scrapers for 3 starter sources: Serper search, generic company website, public LinkedIn (via Proxycurl).
- [ ] Per-tenant proxy pool support (customers bring their own residential proxies — this is best practice for outreach tools).
- [ ] Rate limiter — per-tenant, per-source. Sane defaults.
- [ ] UI: "Lead Sources" — customer picks which sources to scrape from.
- [ ] UI: "ICP Builder" — fields for industry, size, geo, signals.
- [ ] Lead deduplication (by email + by domain).

**Exit criterion**: customer defines an ICP, presses Run, and 50 candidate leads appear in their dashboard.

### Phase 3 — LangGraph Agent (kaymen99 integration) (Week 7–9)
- [ ] Vendor the LangGraph nodes from kaymen99/sales-outreach-automation-langgraph. **Read its licence first**; if absent or restrictive, treat as inspiration only and rewrite. Reach out to the author for a relicence if you intend to fork directly.
- [ ] Replace direct Gemini calls with LiteLLM so the customer chooses provider per-campaign.
- [ ] Add the new "Niche Detection" node.
- [ ] Add per-campaign style guides (customer pastes 3 of their best historical emails, we extract their voice).
- [ ] RAG pipeline: customer uploads case studies / past wins → chunked → pgvector → injected at personalisation time.
- [ ] Generated outputs (report, email draft, interview script) saved to S3 with signed URLs.

**Exit criterion**: pipeline produces a personalised, on-tone email draft for a real lead.

### Phase 4 — Send + Reply + Follow-up Engine (Week 10–12)
- [ ] Sender service that uses connected Gmail/Graph mailbox.
- [ ] Per-tenant daily send caps (default 50/day per mailbox; tunable).
- [ ] Throttled, jittered send schedule (no bursts).
- [ ] Open/click tracking pixel + redirect (with disclosure).
- [ ] Reply detection via Gmail Pub/Sub or IMAP IDLE.
- [ ] Reply classifier (LLM): positive / negative / OOO / question / unsubscribe.
- [ ] Auto-stop sequence on positive/negative.
- [ ] Auto-honour unsubscribe (legally required — CAN-SPAM, GDPR).
- [ ] Follow-up scheduler (Celery beat) with configurable cadence.
- [ ] Each follow-up regenerated with the latest context.

**Exit criterion**: a sequence of 4 emails fires across 14 days, stops on reply, logs everything.

### Phase 5 — Meeting Booking + CRM Sync (Week 13–14)
- [ ] Calendar OAuth (Phase 1 already has the connection — now use it).
- [ ] Scheduling agent: parses positive replies, proposes 3 slots within next 5 working days.
- [ ] Sends ICS attachment + tentative event.
- [ ] Confirms event on counter-reply.
- [ ] CRM sync: HubSpot, Airtable, Google Sheets, Salesforce. Status updates flow both ways.

**Exit criterion**: a positive reply ends with a booked meeting on both calendars and an updated CRM row.

### Phase 6 — Audit Log + Notifications (Week 15)
- [ ] Append-only audit table with hash chain.
- [ ] Filterable audit viewer in dashboard.
- [ ] Real-time notifications: WebSocket channel per tenant for live events ("new reply", "meeting booked", "campaign error").
- [ ] Email digest (daily summary) to customer's primary user.
- [ ] Slack integration (optional) for the same notifications.
- [ ] CSV / JSON audit export.

### Phase 7 — Billing + Plans (Week 16)
- [ ] Stripe Billing integration.
- [ ] Plan tiers (Starter / Growth / Scale) with usage limits.
- [ ] Usage metering (sends, leads scraped, LLM tokens) — meter via a `usage_events` table.
- [ ] Plan-gated features (e.g. CRM sync = Growth+).
- [ ] In-app billing portal.

**This is the V1 launch point.** Stop adding features. Talk to users.

### Phase 8 — Hardening & Launch (Week 17–18)
- [ ] Security audit (you, ideally also a paid pentest later).
- [ ] Load test (k6 / Locust).
- [ ] DSAR / data export endpoints (GDPR right to access).
- [ ] Data deletion flow (GDPR right to be forgotten — note: can't delete from immutable audit log; document this in your privacy policy).
- [ ] Privacy policy, ToS, DPA template (get a lawyer).
- [ ] Status page.
- [ ] Onboarding flow (interactive tour).
- [ ] Docs site.

### Phase 9 (V2) — Self-Hosted Enterprise Tier (Month 6+)
- [ ] Licence-key issuance tool.
- [ ] Self-hosted Docker bundle.
- [ ] Heartbeat + revocation infrastructure.
- [ ] Nuitka/Cython compilation for sensitive modules.
- [ ] Customer-managed encryption keys (CMEK).
- [ ] SAML SSO.
- [ ] Audit log export to customer's SIEM.

### Phase 10 (V2) — Quality of Life
- [ ] Mailbox warmup integration.
- [ ] A/B testing of subject lines / opening lines.
- [ ] Multi-channel (LinkedIn DM via partner like Heyreach, Twitter DM).
- [ ] Team collaboration (assign leads, comment threads).
- [ ] White-label / agency mode.

---

## 8. Repository Structure

```
outreach-os/
├── apps/
│   ├── api/                      # FastAPI backend
│   │   ├── src/
│   │   │   ├── core/             # config, db, auth, tenancy, audit
│   │   │   ├── domain/           # SQLAlchemy models + Pydantic schemas
│   │   │   ├── services/         # business logic
│   │   │   │   ├── scraping/     # wraps Scrapling
│   │   │   │   ├── agents/       # LangGraph graphs + nodes
│   │   │   │   ├── mail/         # send / receive / classify
│   │   │   │   ├── calendar/
│   │   │   │   ├── crm/
│   │   │   │   └── billing/
│   │   │   ├── api/              # FastAPI routers (REST endpoints)
│   │   │   ├── workers/          # Celery tasks
│   │   │   └── main.py
│   │   ├── tests/
│   │   ├── alembic/
│   │   └── pyproject.toml
│   │
│   ├── web/                      # Next.js frontend
│   │   ├── src/
│   │   │   ├── app/              # App Router routes
│   │   │   ├── components/
│   │   │   ├── lib/              # API client, auth, utils
│   │   │   └── styles/
│   │   ├── public/
│   │   └── package.json
│   │
│   └── licence-issuer/           # Phase 9 — internal tool
│       └── …
│
├── packages/
│   ├── shared-types/             # OpenAPI-generated TS types from FastAPI
│   └── shared-config/
│
├── infra/
│   ├── docker/
│   │   ├── docker-compose.dev.yml
│   │   └── Dockerfile.api
│   │   └── Dockerfile.worker
│   │   └── Dockerfile.web
│   ├── fly/                      # fly.toml per app
│   └── github/
│       └── workflows/
│
├── docs/
│   ├── architecture.md
│   ├── runbook.md
│   └── threat-model.md
│
├── .env.example
├── README.md
└── LICENCE
```

---

## 9. Security & Compliance Checklist (Don't Skip)

- [ ] All secrets encrypted at rest with per-tenant DEKs.
- [ ] Postgres RLS enforced; tested.
- [ ] Rate limiting per tenant *and* per IP.
- [ ] CSRF protection (SameSite cookies + double-submit token).
- [ ] HTTPS everywhere. HSTS. Secure cookies.
- [ ] Dependency scanning (Dependabot + `pip-audit`).
- [ ] SAST (Bandit for Python, ESLint security rules for TS).
- [ ] Audit log is append-only (Postgres role permissions enforced).
- [ ] PII redaction in application logs.
- [ ] DPA with sub-processors (LLM providers, scraping APIs, etc.).
- [ ] CAN-SPAM compliance: real physical address in email footer, working unsubscribe.
- [ ] GDPR: lawful basis documented; DPIA done; right-to-access, right-to-deletion endpoints; EU data residency option for enterprise.
- [ ] India DPDP Act 2023 compliance (you're in Delhi — applies to Indian customers).
- [ ] LinkedIn ToS: never scrape directly. Use compliant resellers only.
- [ ] No storing of plaintext OAuth tokens. Refresh-token rotation.
- [ ] Webhook signatures verified on all incoming events.

---

## 10. Estimated Costs (Solo Dev, V1, ~50 customers)

Rough monthly burn at V1 launch:

| Item | Monthly |
|---|---|
| Fly.io compute (API + workers + web) | $40–80 |
| Postgres (managed) | $25–50 |
| Redis (managed) | $15 |
| S3 / R2 storage | $5–10 |
| Sentry | Free tier or $26 |
| LLM costs (passed through to customers) | variable |
| Scraping APIs (Proxycurl etc., passed through) | variable |
| Domain + email infra (transactional only) | $5 |
| Stripe fees | 2.9% + 30¢ per txn |
| **Total fixed** | **~$120–200/mo** |

LLM and scraping costs should be either passed through or built into your pricing tiers. Don't eat them.

---

## 11. The Three Hardest Things You're Underestimating

1. **Reply detection accuracy.** "Out of office" replies that look positive will trigger your "stop sequence" logic and waste opportunities. Build a small labelled dataset early. Don't trust the LLM blindly — wrap it with rule-based pre-filters for OOO patterns.
2. **Respecting unsubscribes globally across campaigns and tenants.** If a contact unsubscribes from Customer A, they should NOT be re-contacted by Customer A's other campaigns. (Cross-tenant unsubscribe is a separate question; legally, no — Customer A's suppression doesn't bind Customer B.)
3. **Cost runaway from LLM calls.** A single buggy loop can rack up hundreds of dollars in an hour. Hard per-tenant per-day spending caps on day one, with circuit breakers.

---

## 12. What Success Looks Like at MVP

You can demo this end-to-end:
1. Sign up as a new tenant.
2. Connect a Gmail mailbox.
3. Add API keys (LLM, Proxycurl, Serper).
4. Define an ICP: "B2B SaaS companies, 20–200 employees, USA, hiring for marketing roles."
5. Press "Find leads" — 30 candidates appear in 2 minutes.
6. Press "Generate outreach" — personalised emails draft for each.
7. Approve a campaign — 5 emails go out today, 5 tomorrow, etc.
8. A reply comes in — auto-classified, sequence stopped, slack notification fires.
9. A meeting gets booked on the connected calendar.
10. Every step shows up in the audit log.

If that demo works reliably, you have a product. Sell it.

---

## 13. References Cited
- Scrapling — github.com/D4Vinci/Scrapling (BSD-3-Clause)
- sales-outreach-automation-langgraph — github.com/kaymen99/sales-outreach-automation-langgraph (licence not declared as of writing — verify before forking)
- LangGraph docs — langchain-ai.github.io/langgraph
- LiteLLM — github.com/BerriAI/litellm
- Postgres RLS — postgresql.org/docs/current/ddl-rowsecurity.html
- Stripe Billing — stripe.com/docs/billing
- CAN-SPAM — ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business
- GDPR — gdpr.eu
- India DPDP Act 2023 — meity.gov.in (search "DPDP")
# New Phase 

