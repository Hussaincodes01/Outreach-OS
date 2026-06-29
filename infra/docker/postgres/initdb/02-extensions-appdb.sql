-- 02-extensions-appdb.sql
-- Runs after 01-create-app-role.sql has created the `outreach` and
-- `outreach_test` databases. The earlier 00-extensions.sql only installed
-- the extensions into the bootstrap `postgres` database (the default
-- POSTGRES_DB), which the application never connects to. Extensions are
-- per-database, so we must (re)create them inside the actual app databases.
--
-- These run as the bootstrap superuser during initdb, which is required:
-- pgcrypto and vector cannot be created by the non-superuser app role.
--
-- Idempotent: re-running is a no-op.

\connect outreach
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

\connect outreach_test
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
