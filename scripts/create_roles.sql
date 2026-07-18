-- scripts/create_roles.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- One-time setup: create the tapply_app PostgreSQL role.
--
-- Run this script as a superuser ONCE per environment, BEFORE running
-- `alembic upgrade head`.  The migration grants privileges to tapply_app
-- but does not create it (role creation and credential management must not
-- live inside a versioned migration that can be re-run in CI).
--
-- Usage:
--   psql -U postgres -d tapply -f scripts/create_roles.sql
--
-- After running this script, set tapply_app's password:
--   psql -U postgres -c "ALTER ROLE tapply_app WITH PASSWORD 'your-strong-password';"
-- Then set DATABASE_URL=postgresql://tapply_app:<password>@<host>/<db> in .env.
--
-- ─────────────────────────────────────────────────────────────────────────────
-- Role hierarchy reminder:
--   postgres (superuser)  — runs migrations, owns tables, owns SECURITY DEFINER fns
--   tapply_app            — application runtime, RLS enforced, no BYPASSRLS
--   tapply_admin (future) — internal tooling only, BYPASSRLS, never in app pool
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tapply_app') THEN
        CREATE ROLE tapply_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
        RAISE NOTICE 'Role tapply_app created. Set a password with: ALTER ROLE tapply_app WITH PASSWORD ''...'';';
    ELSE
        RAISE NOTICE 'Role tapply_app already exists — skipping creation.';
    END IF;
END
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- Platform admin role (future — do not grant BYPASSRLS until internal
-- tooling infrastructure is in place and credentials are in a separate
-- secrets manager path from the app's DATABASE_URL).
--
-- Uncomment when ready:
-- DO $$
-- BEGIN
--     IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tapply_admin') THEN
--         CREATE ROLE tapply_admin WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
--         RAISE NOTICE 'Role tapply_admin created. Store credentials SEPARATELY from tapply_app.';
--     END IF;
-- END
-- $$;
