-- bootstrap-extensions.sql
-- Pre-migration script run by the bootstrap superuser. Creates the
-- PostgreSQL extensions that the application needs. These extensions
-- are cluster-level and require SUPERUSER to install; the migration
-- scripts that follow are run by the non-superuser `outreach` role.
--
-- Idempotent: re-running is a no-op.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
