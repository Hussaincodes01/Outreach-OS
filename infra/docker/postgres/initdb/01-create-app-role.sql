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

-- The app role can connect, use the public schema, and run DML on
-- everything that exists or will exist. Migrations (DDL like CREATE
-- EXTENSION) need CREATE on the database; we grant that so the role
-- can run the test-suite migrations as well. (Extensions themselves
-- are installed by 00-extensions.sql as the superuser.)
GRANT CONNECT, CREATE ON DATABASE outreach TO outreach;
GRANT CONNECT, CREATE ON DATABASE outreach_test TO outreach;
GRANT USAGE, CREATE ON SCHEMA public TO outreach;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO outreach;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO outreach;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO outreach;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO outreach;
