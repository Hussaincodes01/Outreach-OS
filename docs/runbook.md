# Runbook

Operating Outreach OS: deploying it, checking it came up, and the failure modes
that have actually bitten us.

---

## Deploy

The build context must be the repository root.

```bash
cp .env.production.example .env.production   # then fill in real secrets
docker compose -f infra/docker/docker-compose.prod.yml up -d --build
```

This starts six services: `postgres`, `redis`, a one-shot `migrate`, then
`api`, `worker` and `beat`, plus `web`. Only `api` (8000) and `web` (3000) are
published to the host; the database and Redis stay on the internal network.

### Generating secrets

```bash
# JWT_SECRET, INBOUND_WEBHOOK_SECRET, NEXTAUTH_SECRET
openssl rand -hex 32

# VAULT_MASTER_KEY (must decode to >= 32 bytes)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Rotating `VAULT_MASTER_KEY` makes every stored tenant credential
undecryptable.** There is no re-wrap path yet. Treat it as permanent for the
life of the deployment, and back it up separately from the database.

### Required in production

The API refuses to boot with an insecure or incomplete configuration — by
design, so a misconfiguration fails at startup rather than silently at
runtime. `ENVIRONMENT=production` requires:

| Variable | Why it is enforced |
| --- | --- |
| `JWT_SECRET` | Must be >= 16 chars. The default would let anyone mint tokens |
| `VAULT_MASTER_KEY` | Must be base64 decoding to >= 32 bytes |
| `INBOUND_WEBHOOK_SECRET` | HMAC for inbound reply webhooks; without it anyone can post replies |
| `CORS_ALLOWED_ORIGINS` | The browser cannot call the API without it |
| `PUBLIC_BASE_URL` | Must not be localhost — tracking and unsubscribe links embed it |
| `CELERY_TASK_ALWAYS_EAGER` | Must be `false`, or background jobs run inside web requests |

`CORS_ALLOWED_ORIGINS` accepts a comma-separated list
(`https://app.example.com, https://admin.example.com`) or a JSON array.

Provider API keys are **not** environment variables. Each workspace adds its
own under Settings → Integrations, and they are stored encrypted per tenant.

---

## Verify a deployment

```bash
docker compose -f infra/docker/docker-compose.prod.yml ps      # api + postgres healthy
docker compose -f infra/docker/docker-compose.prod.yml logs migrate | tail -5
curl -fsS http://localhost:8000/health                          # {"status":"ok"}
```

`migrate` is expected to show as `Exited (0)` — it is a one-shot job.

Then confirm the tenancy layer is really on, which is the property most worth
checking after any database change:

```bash
docker compose -f infra/docker/docker-compose.prod.yml exec postgres \
  psql -U postgres -d outreach -tAc \
  "SELECT count(*) FILTER (WHERE relrowsecurity) || ' of ' || count(*) || ' tables have RLS'
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='public' AND c.relkind='r'"
```

Expect 29 of 33. The four without RLS are `plan`, `alembic_version`,
`tenant` (the master table, gated at the application layer) and
`billing_portal_token` (the token itself is the capability).

---

## Database roles

Two roles, and the distinction matters:

- **`postgres`** — superuser. Runs migrations only. Migration `0010` sets
  `auth_user_by_email` to be owned by a superuser so `SECURITY DEFINER`
  actually bypasses RLS; a non-superuser cannot do this.
- **`outreach`** — `NOSUPERUSER NOBYPASSRLS`. What the API, worker and beat
  connect as. Superusers bypass RLS unconditionally, so running the app as one
  would silently disable tenant isolation.

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
docker compose -f infra/docker/docker-compose.prod.yml exec -T postgres \
  psql -U postgres -d outreach < infra/docker/postgres/initdb/03-grants-appdb.sql
```

### API exits at startup with a config error

Read the message — it lists every problem at once. Most common is
`CORS_ALLOWED_ORIGINS` being unset, or `PUBLIC_BASE_URL` still pointing at
localhost.

### `must be able to SET ROLE "postgres"` during migration

Migrations are running as the app role. They must run as the superuser; the
compose file overrides `DATABASE_URL` for the `migrate` service only.

### Drafts fail with "No … API key connected"

Working as intended: that workspace has not connected a provider key. It is a
`428`, not a `500`. Point the user at Settings → Integrations.

### Drafts fail only for one provider

Use the Test button on the credential — it makes a real call. Expired keys,
exhausted quota, and models not enabled for that account all surface there.

### StealthyFetcher cannot find a browser

Chromium lives at `/ms-playwright` (set by `PLAYWRIGHT_BROWSERS_PATH`) so the
unprivileged `app` user can execute it. If this breaks, confirm the path exists
and is world-readable inside the container.

### Port already allocated

Something else is on 3000 or 8000. Either stop it, or publish elsewhere with an
override file — Compose *merges* port lists, so you must use `!override` to
replace rather than append:

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

---

## Backups

`postgres-data` is a named Docker volume. Nothing backs it up automatically.

```bash
# Dump
docker compose -f infra/docker/docker-compose.prod.yml exec -T postgres \
  pg_dump -U postgres -Fc outreach > outreach-$(date +%F).dump

# Restore into an empty database
docker compose -f infra/docker/docker-compose.prod.yml exec -T postgres \
  pg_restore -U postgres -d outreach --clean --if-exists < outreach-2026-01-01.dump
```

A dump is useless without the matching `VAULT_MASTER_KEY` — stored credentials
cannot be decrypted without it. Back up the key alongside, but not in the same
place.

---

## Not yet covered

Honest gaps, so nobody assumes otherwise:

- **No TLS.** The compose stack serves plain HTTP. Put a reverse proxy in
  front; the API already trusts `X-Forwarded-*` via
  `--forwarded-allow-ips=*`, which is only safe behind a proxy you control.
- **Bundled Postgres credentials are `outreach`/`outreach`.** Fine on an
  internal network, not for a real deployment. Use a managed database and drop
  the `postgres` and `redis` services from the compose file.
- **No monitoring.** `SENTRY_DSN` is unset by default; nothing scrapes metrics.
- **No incident history.** This section should grow with real postmortems.
