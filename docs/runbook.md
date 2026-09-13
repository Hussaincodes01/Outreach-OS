# Runbook

Operating Outreach OS: deploying it, checking it came up, and the failure modes
that have actually bitten us.

**There is no authentication.** Every request acts as the one built-in local
workspace. Do not bind the stack's ports to a public interface or otherwise
expose it to the internet without putting an authenticating reverse proxy
(nginx/Caddy with basic auth, a Tailscale/WireGuard tunnel, an OAuth-gated
proxy, ...) in front of it. See [docs/threat-model.md](threat-model.md).

---

## Deploy

The build context must be the repository root.

```bash
npm run setup                          # creates .env, fills VAULT_MASTER_KEY / INBOUND_WEBHOOK_SECRET
# edit .env: add provider key(s) — optional, see SETUP.md
npm start                              # docker compose up -d --build
```

`npm start` is `docker compose up -d --build` against the root
`docker-compose.yml`. It starts `postgres`, `redis`, `minio`, a one-shot
`migrate`, then `api`, `worker`, `beat`, and `web`. Only `api` (8000) and
`web` (3000) are published to the host; Postgres, Redis and MinIO stay on
the internal Docker network.

Add `--profile e2e` (or run `docker compose --profile e2e up -d --build`
directly) to also start GreenMail, a local SMTP+IMAP server used by the
smoke test and by manual end-to-end testing on host ports 3025 (SMTP) and
3143 (IMAP).

Stop the stack with `npm stop`; follow API/worker/beat logs with
`npm run logs`.

### Generating secrets

`npm run setup` generates these automatically; only needed by hand if you
want to rotate one:

```bash
# INBOUND_WEBHOOK_SECRET
openssl rand -hex 32

# VAULT_MASTER_KEY (must decode to >= 32 bytes)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Rotating `VAULT_MASTER_KEY` makes every stored credential (mailbox
SMTP/IMAP passwords, any provider key stored via the app rather than
`.env`) undecryptable.** There is no re-wrap path yet. Treat it as permanent
for the life of the deployment, and back it up separately from the database.

### Required in production

The API refuses to boot with an insecure or incomplete configuration when
`ENVIRONMENT=production` — by design, so a misconfiguration fails at
startup rather than silently at runtime:

| Variable | Why it is enforced |
| --- | --- |
| `VAULT_MASTER_KEY` | Must be base64 decoding to >= 32 bytes |
| `INBOUND_WEBHOOK_SECRET` | HMAC for the inbound reply webhook; without it anyone can post replies |
| `CORS_ALLOWED_ORIGINS` | The browser cannot call the API without it |
| `PUBLIC_BASE_URL` | Must not be localhost — tracking and unsubscribe links embed it |
| `CELERY_TASK_ALWAYS_EAGER` | Must be `false`, or background jobs run inside web requests |

`CORS_ALLOWED_ORIGINS` accepts a comma-separated list
(`https://app.example.com, https://admin.example.com`) or a JSON array.

Provider API keys are environment variables, not something entered through
the UI. Set them in `.env` (or the container environment) and restart the
API — see [SETUP.md](../SETUP.md#provider-api-keys-live-in-env).

---

## Verify a deployment

```bash
cd /d/OutreachOS/Outreach-OS
npm run setup
docker compose config -q
docker compose --profile e2e up -d --build
docker compose ps
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/health/ready
curl -fsS http://localhost:8000/v1/tenants/me
curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:3000/dashboard
docker compose logs migrate | tail -5
docker compose logs beat | grep -E "send_due|poll_inboxes" | head
```

Expected: every service `running`/`healthy` (`migrate` shows `Exited (0)` —
it is a one-shot job); both health checks return `{"status":"ok"}`;
`/v1/tenants/me` returns slug `local`; the web dashboard responds `200`;
the beat log shows both `send_due` and `poll_inboxes` on the schedule.

For a fuller proof — a real ICP, a CSV lead import, a real SMTP send and
IMAP reply capture against GreenMail, and (if a provider key is set) a full
draft → send → reply loop — run the smoke script:

```bash
npm run smoke
```

See `scripts/e2e_smoke.py` for exactly what each of its 11 checks proves;
it prints one `PASS`/`FAIL`/`SKIP` line per check and exits non-zero on any
`FAIL`.

Then confirm the tenancy layer is really on, which is the property most worth
checking after any database change:

```bash
docker compose exec postgres \
  psql -U postgres -d outreach -tAc \
  "SELECT count(*) FILTER (WHERE relrowsecurity) || ' of ' || count(*) || ' tables have RLS'
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='public' AND c.relkind='r'"
```

Expect `29 of 33`. The four without RLS are `plan`, `alembic_version`,
`tenant` (the master table, gated at the application layer) and
`billing_portal_token` (the token itself is the capability). `plan` and
`billing_portal_token` are unused tables left in place (see
[docs/architecture.md](architecture.md)) rather than dropped.

---

## Database roles

Two roles, and the distinction matters:

- **`postgres`** — superuser. Runs migrations only. Migration `0010` sets
  `auth_user_by_email` to be owned by a superuser so `SECURITY DEFINER`
  actually bypasses RLS; a non-superuser cannot do this.
- **`outreach`** — `NOSUPERUSER NOBYPASSRLS`. What the API, worker and beat
  connect as. Superusers bypass RLS unconditionally, so running the app as one
  would silently disable the tenancy boundary that still exists underneath
  the single local workspace.

Both are created by `infra/docker/postgres/initdb`, which runs **only on an
empty data volume**. Changing those scripts has no effect on an existing
deployment — apply the equivalent SQL by hand.

---

## Failure modes

### `permission denied for table ...` on every query

The app role has no privileges in the application database. Schema, table and
sequence grants are stored **per database**; issuing them while connected to
the bootstrap `postgres` database silently grants nothing where it matters.
`03-grants-appdb.sql` connects to each app database. On an already-initialised
volume, apply it manually:

```bash
docker compose exec -T postgres \
  psql -U postgres -d outreach < infra/docker/postgres/initdb/03-grants-appdb.sql
```

### API exits at startup with a config error

Read the message — it lists every problem at once. Most common is
`CORS_ALLOWED_ORIGINS` being unset, or `PUBLIC_BASE_URL` still pointing at
localhost, in a `production` environment.

### `must be able to SET ROLE "postgres"` during migration

Migrations are running as the app role. They must run as the superuser; the
compose file overrides `DATABASE_URL` for the `migrate` service only.

### Drafts fail with a `428`

Working as intended: no LLM provider key is configured. Add
`<PROVIDER>_API_KEY` to `.env` (see [SETUP.md](../SETUP.md#provider-api-keys-live-in-env))
and restart the API (`docker compose restart api worker beat`, or
`npm start` again). The response body names which provider/model was
requested.

### Drafts fail only for one provider

Use the **Test** button on the Integrations page, or
`POST /v1/credentials/providers/{provider}/test` — it makes a real call.
Expired keys, exhausted quota, and models not enabled for that account all
surface there.

### IMAP reply capture never picks anything up

- Confirm the mailbox was created with `imap_host` set —
  `GET /v1/mailboxes` shows `imap_enabled`.
- Gmail/Outlook require an **app password**, not the account password (see
  [README.md](../README.md#mailboxes)); a plain password fails IMAP login
  even though SMTP sending may have worked.
- The beat schedule polls every `INBOX_POLL_INTERVAL_SECONDS` (default
  120s) — check `docker compose logs beat | grep poll_inboxes` for recent
  runs and any login errors.
- Messages are fetched with PEEK and marked `\Seen` only after they are
  durably handled — a reply that keeps reappearing as unseen across polls
  means ingestion is failing after the fetch; check the worker logs.

### A sequence step never sends

- Confirm a mailbox is connected and active (`GET /v1/mailboxes`) — sends
  pick the first active mailbox for the workspace.
- Confirm the mailbox hasn't hit its `daily_send_cap`.
- Check `docker compose logs beat | grep send_due` — `send_due` runs every
  `SEND_DUE_INTERVAL_SECONDS` (default 60s).
- If you've added time-of-day send-window logic on top of this build, make
  sure `SEND_WINDOW_START_HOUR`/`SEND_WINDOW_END_HOUR` in `.env` cover the
  current hour (UTC) — the shipped build does not gate sends by time of day.

### StealthyFetcher cannot find a browser

Chromium lives at `/ms-playwright` (set by `PLAYWRIGHT_BROWSERS_PATH`) so the
unprivileged `app` user can execute it. If this breaks, confirm the path exists
and is world-readable inside the container.

### Port already allocated

Something else is on 3000, 8000, 3025 or 3143. This project's Postgres/Redis
are internal-only in the root stack (no host port), so a collision there
means another `outreach-os` stack is already running. Either stop it, or
publish elsewhere with an override file — Compose *merges* port lists, so
you must use `!override` to replace rather than append:

```yaml
services:
  api:
    ports: !override ["8100:8000"]
  web:
    build:
      args:
        NEXT_PUBLIC_API_URL: http://localhost:8100   # baked in at build time
    ports: !override ["3100:3000"]
```

`NEXT_PUBLIC_API_URL` is inlined into the client bundle during `next build`.
Changing the API's address means rebuilding the web image, not just restarting
it.

If you're running `npm run dev:infra` (native API/web development) *and*
`docker compose --profile e2e`, note both default GreenMail to host ports
3025/3143 — only one can be up at a time.

---

## Backups

`postgres-data` is a named Docker volume. Nothing backs it up automatically.

```bash
# Dump
docker compose exec -T postgres \
  pg_dump -U postgres -Fc outreach > outreach-$(date +%F).dump

# Restore into an empty database
docker compose exec -T postgres \
  pg_restore -U postgres -d outreach --clean --if-exists < outreach-2026-01-01.dump
```

A dump is useless without the matching `VAULT_MASTER_KEY` — stored
credentials (mailbox passwords, any provider key added through the app
instead of `.env`) cannot be decrypted without it. Back up the key
alongside, but not in the same place.

---

## Not yet covered

Honest gaps, so nobody assumes otherwise:

- **No TLS, no authentication.** The compose stack serves plain HTTP with no
  login. Put an authenticating reverse proxy in front for anything beyond
  localhost use; the API already trusts `X-Forwarded-*` via
  `--forwarded-allow-ips=*`, which is only safe behind a proxy you control.
- **Bundled Postgres credentials are `outreach`/`outreach`.** Fine on an
  internal Docker network, not for a database exposed elsewhere. Use a
  managed database and drop the `postgres`/`redis`/`minio` services from the
  compose file if you need that.
- **No monitoring.** `SENTRY_DSN` is unset by default; nothing scrapes metrics.
- **The CRM (Google Sheets) and calendar provider clients are stubs.** The
  CRM sync page is unlinked from the web app's navigation.
- **No incident history.** This section should grow with real postmortems.
