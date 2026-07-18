# Tapply Backend

Multi-tenant SaaS backend. Built with FastAPI + PostgreSQL + SQLAlchemy + Alembic.

---

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ (RLS policies and `gen_random_uuid()` require pg14+)
- A PostgreSQL database created for the app and one for tests

---

## First-time Setup

### 1. Install dependencies

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in your actual database URLs and credentials.
```

Key variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Runtime connection (uses `tapply_app` role) |
| `MIGRATION_DATABASE_URL` | Alembic migrations (superuser — never the app role) |
| `TEST_DATABASE_URL` | pytest (must be a superuser connection) |

### 3. Create the application role

Run this **once per environment** as a superuser, **before** running migrations:

```bash
psql -U postgres -d tapply -f scripts/create_roles.sql
```

Then set a password for `tapply_app`:

```sql
ALTER ROLE tapply_app WITH PASSWORD 'your-strong-password';
```

Update `DATABASE_URL` in `.env` with the new credentials.

### 4. Create databases

```sql
-- As superuser:
CREATE DATABASE tapply;
CREATE DATABASE tapply_test;

-- Grant connect to tapply_app:
GRANT CONNECT ON DATABASE tapply      TO tapply_app;
GRANT CONNECT ON DATABASE tapply_test TO tapply_app;
```

### 5. Run migrations

Migrations must run as a **superuser** (they create tables, enable RLS, and create `SECURITY DEFINER` functions — all of which require elevated privileges).

```bash
# Option A: set MIGRATION_DATABASE_URL in your .env
alembic upgrade head

# Option B: override inline
MIGRATION_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tapply \
    alembic upgrade head
```

> **Why two URLs?**  
> The app connects as `tapply_app` (no DDL rights, RLS enforced). Migrations need superuser DDL rights. Mixing them would either over-privilege the app or under-privilege the migration runner.

---

## Running the Server

```bash
uvicorn app.main:app --reload
```

Verify:

```bash
curl http://localhost:8000/health
# → {"status":"ok"}
```

---

## Running Tests

Ensure `TEST_DATABASE_URL` points to a **superuser connection** on the test database and that migrations have been applied there:

```bash
MIGRATION_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tapply_test \
    alembic upgrade head
```

Then:

```bash
pytest tests/test_rls.py -v
```

Expected output:

```
tests/test_rls.py::test_org_isolation                        PASSED
tests/test_rls.py::test_lookup_staff_org_bypasses_rls        PASSED
tests/test_rls.py::test_create_organization_bypasses_rls     PASSED
tests/test_rls.py::test_app_role_denied_direct_staff_users   PASSED
```

> Tests 2–4 require the `tapply_app` role to exist (step 3 above). They skip with a clear message if the role is missing.

---

## Security Architecture

### Row-Level Security

Every table with `org_id` (or reachable via FK) has `FORCE ROW LEVEL SECURITY`. All RLS policies filter on:

```sql
NULLIF(current_setting('app.current_org_id', true), '')::uuid
```

`SET LOCAL` scopes the context to the current transaction only — a recycled pooled connection never inherits a previous tenant's context.

### The RLS Bootstrap Problem

Two scenarios require database access *before* the org context can be set:

| Scenario | Solution |
|---|---|
| **Staff login** — must read `staff_users` to find `org_id` | `auth.lookup_staff_org(email)` — `SECURITY DEFINER` |
| **Org creation** — must INSERT into `organizations` before org exists | `auth.create_organization(...)` — `SECURITY DEFINER` |

Both functions run as their owner (the superuser who ran the migration), bypassing `FORCE ROW LEVEL SECURITY`. The `tapply_app` role only has `EXECUTE` on these specific functions — no direct table access.

### Why Not a Bypass Role?

A `BYPASSRLS` application role would mean a credential leak exposes the entire database across all tenants. With `SECURITY DEFINER` functions, a leaked `tapply_app` credential only grants access to two narrowly-scoped function calls. See the implementation plan for the full three-option analysis.

### Platform Admin Access (Future)

Cross-org access for support/billing/debugging will use a separate `tapply_admin` PostgreSQL role with `BYPASSRLS`. This role:

- Is **never** in the application's connection pool.
- Is used only from internal tooling on a separate internal host.
- Has credentials stored in a separate secrets manager path from `DATABASE_URL`.

The `tapply_admin` role stub is in `scripts/create_roles.sql` (commented out — uncomment when the internal tooling is ready).

### Auth Method

Step 2 will use **Clerk** (external auth provider). Clerk verifies credentials; Tapply only receives a verified JWT containing the user's email. No password hashes are stored in `staff_users`.

---

## Project Structure

```
tapply_backend/
├── alembic/
│   ├── env.py                    # Migration environment, reads MIGRATION_DATABASE_URL
│   ├── script.py.mako            # Template for new migrations
│   └── versions/
│       └── 0001_initial_schema.py  # All tables + RLS + SECURITY DEFINER functions
├── app/
│   ├── config.py                 # Settings (pydantic-settings, reads .env)
│   ├── main.py                   # FastAPI app, GET /health
│   ├── db/
│   │   ├── base.py               # DeclarativeBase
│   │   └── session.py            # Engine, SessionLocal, set_org_context()
│   └── models/
│       ├── organization.py
│       ├── staff_user.py
│       ├── stand.py
│       ├── card.py
│       ├── form_schema.py
│       └── submission.py
├── scripts/
│   └── create_roles.sql          # One-time role creation (run before migrations)
├── tests/
│   ├── conftest.py               # owner_conn fixture (superuser, autorollback)
│   └── test_rls.py               # 4 RLS + privilege-boundary tests
├── .env.example
├── alembic.ini
└── requirements.txt
```

---

## What's Not Built Yet (Step 2+)

- Authentication (Clerk JWT middleware)
- Public form endpoint (`POST /submit/{token}`)
- Admin dashboard API
- Staff user management endpoints
- Form schema CRUD
- Submission workflow endpoints
