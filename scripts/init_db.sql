-- pgcrypto extension for gen_random_uuid().
-- Schema is managed by Alembic migrations (see migrations/versions/).
-- This file only ensures the extension exists before migrations run.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
