-- 01-create-app-role.sql
-- Bootstrap script: runs once on first container start as the
-- `postgres` superuser. It creates the non-superuser app role and
-- the two databases we use (main + tests).
--
-- Why a non-superuser: PostgreSQL superusers always bypass RLS
-- (rolbypassrls = true is implicit). The whole point of Phase 0 is
-- defense-in-depth via RLS, so the *application* role must be
-- subject to row-level security. A separate `outreach_admin` role
-- is granted to migrations so they can DDL freely; the app itself
-- connects as the regular `outreach` role.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'outreach') THEN
    CREATE ROLE outreach WITH LOGIN PASSWORD 'outreach' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  ELSE
    -- Defensive: re-assert non-superuser + no BYPASSRLS in case the
    -- container was rebuilt but the role was somehow re-granted.
    ALTER ROLE outreach WITH NOSUPERUSER NOBYPASSRLS;
  END IF;
END
$$;

-- Owned by the postgres superuser, but the app role has CONNECT + CRUD
-- via the GRANTs at the bottom of this script.
SELECT 'CREATE DATABASE outreach OWNER postgres'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'outreach')
\gexec

SELECT 'CREATE DATABASE outreach_test OWNER postgres'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'outreach_test')
\gexec

-- Database-level grants. These live in the shared catalog, so they can be
-- issued from any database.
GRANT CONNECT, CREATE ON DATABASE outreach TO outreach;
GRANT CONNECT, CREATE ON DATABASE outreach_test TO outreach;

-- NOTE: schema-, table- and sequence-level grants are NOT cluster-wide — they
-- are stored per database. Issuing them here would only affect the bootstrap
-- `postgres` database, which the application never connects to, leaving the
-- app role unable to read its own tables. They are applied inside each app
-- database by 03-grants-appdb.sql instead.
