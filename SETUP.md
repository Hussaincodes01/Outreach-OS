# Outreach OS Setup And Environment Tutorial

This guide explains how to configure Outreach OS without exposing secrets.

## Never Commit Secrets

Do not commit:

- `.env`
- `.env.local`
- provider API keys
- OAuth client secrets
- JWT secrets
- database URLs with real credentials
- private keys
- production logs
- local virtual environments
- build caches

The repository includes `.gitignore` rules for common secret and generated files.

## Create Your Local `.env`

Copy the template:

```bash
copy .env.example .env
```

On macOS/Linux:

```bash
cp .env.example .env
```

Then edit `.env` locally. Keep real values on your machine only.

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `ENVIRONMENT` | Runtime mode, usually `development`, `test`, or `production` |
| `DATABASE_URL` | Async SQLAlchemy PostgreSQL URL used by the API |
| `DATABASE_URL_SYNC` | Sync PostgreSQL URL for tooling that cannot use asyncpg |
| `DATABASE_URL_ADMIN` | Admin database URL for migrations/bootstrap only |
| `TEST_DATABASE_URL` | Test database URL |
| `TEST_DATABASE_URL_ADMIN` | Admin URL for test setup |
| `REDIS_URL` | Redis URL for cache/rate-limit use |
| `CELERY_BROKER_URL` | Celery broker URL |
| `CELERY_RESULT_BACKEND` | Celery result backend URL |
| `JWT_SECRET` | Secret used to sign local JWTs |
| `JWT_ALG` | JWT algorithm, typically `HS256` |
| `JWT_ACCESS_TTL_MINUTES` | Access token lifetime |
| `JWT_REFRESH_TTL_DAYS` | Refresh token lifetime |
| `VAULT_MASTER_KEY` | Local key used to wrap tenant credential encryption |
| `LOG_LEVEL` | API log verbosity |
| `NEXT_PUBLIC_API_URL` | Browser-visible API base URL. Inlined into the client bundle at build time |
| `NEXTAUTH_URL` | NextAuth app URL |
| `NEXTAUTH_SECRET` | Secret used by NextAuth |
| `CORS_ALLOWED_ORIGINS` | Comma-separated browser origins allowed to call the API. **Required in production** |
| `PUBLIC_BASE_URL` | Public API URL embedded in tracking and unsubscribe links. **Required in production**, and may not be localhost |
| `INBOUND_WEBHOOK_SECRET` | HMAC secret verifying inbound reply webhooks. **Required in production** |
| `CELERY_TASK_ALWAYS_EAGER` | Runs background jobs inline. Must be `false` in production |

## Provider API Keys Are Not Environment Variables

Outreach OS is bring-your-own-key. LLM and scraping keys are added **in the
app** (Settings → Integrations), encrypted with a per-tenant key, and never
returned by the API.

Do not set `OPENAI_API_KEY` or similar in the environment expecting it to be
used — it will be ignored. A shared worker process serves many tenants
concurrently, so an environment key could be applied to the wrong tenant's
request; the resolver reads only from the encrypted per-tenant vault.

The one exception is `OUTREACH_TEST_OPENAI_KEY`, used solely by the live-provider
test to prove the BYOK path works end to end.

## Generate Safe Local Secrets

Use random values for local secrets:

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

For Fernet-compatible vault keys, use Python:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Start Local Infrastructure

```bash
npm run dev:infra
```

This starts local services through Docker Compose, including PostgreSQL, Redis, MinIO, and MailHog when configured by the compose file.

## Install API Dependencies

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

On macOS/Linux:

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

> **Windows:** `litellm` publishes no Windows wheel, and building its sdist
> requires a Rust toolchain, so this install usually fails. Run the API in
> Docker instead — see the Docker section of [README.md](README.md). The web
> app installs and runs natively on Windows without trouble.

## Install Web Dependencies

The repo uses npm workspaces, so install once from the root:

```bash
npm install
```

## Run Tests

API — requires the dev infrastructure (`npm run dev:infra`) to be running,
since the suite exercises real PostgreSQL RLS:

```bash
npm run test:api
```

Migrations run as the admin role during test setup, which mirrors production:
migration `0010` needs superuser privileges. Set `DATABASE_URL_ADMIN`
accordingly.

Lint and typecheck:

```bash
cd apps/api && ruff check . && mypy src
```

Web — lint, typecheck and build. There is no web unit-test suite yet:

```bash
npm run lint:web
npm run typecheck:web
npm run build:web
```

## Before Pushing

Run:

```bash
git status --short
git check-ignore .env apps/web/.env.local
rg -n --hidden -g '!node_modules' -g '!.git' -g '!.env' -g '!.env.*' -g '!*.log' -g '!*.pyc' -g '!__pycache__/**' "API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY|DATABASE_URL|BEGIN PRIVATE"
```

The scan may show placeholder examples in docs or CI. It must not show real production secrets.

If a secret was committed, rotate it immediately before publishing the repository.
