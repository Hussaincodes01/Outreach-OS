-- 03-grants-appdb.sql
-- Per-database privileges for the non-superuser app role.
--
-- Schema, table and sequence grants are stored PER DATABASE (unlike the
-- CONNECT/CREATE-on-database grants in 01, which live in the shared catalog).
-- They therefore have to be issued from inside each application database.
--
-- Since PostgreSQL 15 the `public` schema no longer grants CREATE to PUBLIC,
-- so without the USAGE/CREATE grant below the app role cannot create tables
-- (test-suite migrations fail) and — because migrations in production run as
-- the `postgres` superuser — the tables end up owned by `postgres` with no
-- privileges for `outreach`, making every runtime query fail with
-- "permission denied for table ...".
--
-- Runs as the bootstrap superuser during initdb. Idempotent.

\connect outreach

GRANT USAGE, CREATE ON SCHEMA public TO outreach;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO outreach;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO outreach;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO outreach;
-- Objects created later by the migration role (postgres in production,
-- outreach in the test suite) must also be reachable by the app role.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO outreach;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO outreach;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO outreach;
ALTER DEFAULT PRIVILEGES FOR ROLE outreach IN SCHEMA public GRANT ALL ON TABLES TO outreach;
ALTER DEFAULT PRIVILEGES FOR ROLE outreach IN SCHEMA public GRANT ALL ON SEQUENCES TO outreach;

\connect outreach_test

GRANT USAGE, CREATE ON SCHEMA public TO outreach;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO outreach;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO outreach;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO outreach;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO outreach;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO outreach;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO outreach;
ALTER DEFAULT PRIVILEGES FOR ROLE outreach IN SCHEMA public GRANT ALL ON TABLES TO outreach;
ALTER DEFAULT PRIVILEGES FOR ROLE outreach IN SCHEMA public GRANT ALL ON SEQUENCES TO outreach;
