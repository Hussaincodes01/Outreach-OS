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
| `NEXT_PUBLIC_API_URL` | Browser-visible API base URL for the web app |
| `NEXTAUTH_URL` | NextAuth app URL |
| `NEXTAUTH_SECRET` | Secret used by NextAuth |

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

## Install Web Dependencies

```bash
cd apps/web
npm install
```

## Run Tests

API:

```bash
npm run test:api
```

Web:

```bash
cd apps/web
npm test
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
