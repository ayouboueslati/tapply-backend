"""
app/db/session.py
─────────────────
Database engine and session factory for the Tapply application.

Connection role:
  The engine connects as ``tapply_app`` (via DATABASE_URL).  This role is
  subject to full Row-Level Security on every table.  A transaction MUST call
  ``set_org_context(session, org_id)`` before querying any RLS-protected table.

RLS bootstrap pattern (Step 2 — Clerk external auth):
  After the Clerk JWT is verified and the user's email is extracted:

    with SessionLocal() as session:
        with session.begin():
            row = session.execute(
                text("SELECT user_id, org_id, role "
                     "FROM auth.lookup_staff_org(:email)"),
                {"email": verified_email},
            ).one()
            set_org_context(session, row.org_id)
            # All subsequent queries are now scoped to row.org_id via RLS.

Org creation pattern (onboarding — Step 2):
  tapply_app cannot INSERT into organizations directly (FORCE RLS blocks it).
  Use the SECURITY DEFINER function instead:

    with SessionLocal() as session:
        with session.begin():
            row = session.execute(
                text(
                    "SELECT org_id, admin_user_id "
                    "FROM auth.create_organization(:name, :status, :email, :role)"
                ),
                {
                    "name":   org_name,
                    "status": "active",
                    "email":  admin_email,
                    "role":   "owner",
                },
            ).one()
            set_org_context(session, row.org_id)
"""

import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# ─── Engine ──────────────────────────────────────────────────────────────────
# Sync engine using psycopg2.  pool_pre_ping detects stale connections
# (important for long-lived pools behind pgBouncer or when the DB restarts).
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
)

# ─── Session factory ─────────────────────────────────────────────────────────
# autocommit=False: every session.begin() / context-manager wraps a real TX.
# autoflush=False:  explicit control; prevents accidental flushes before the
#                   RLS context is set.
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ─── RLS context helper ───────────────────────────────────────────────────────
def set_org_context(session: Session, org_id: uuid.UUID | str) -> None:
    """
    Scope the current database transaction to ``org_id`` via PostgreSQL's
    row-level security system.

    Uses ``SET LOCAL`` so the GUC is automatically cleared at transaction end —
    a recycled pooled connection will never inherit a previous tenant's context.

    Must be called inside an open transaction (i.e. inside a ``session.begin()``
    block or after the session has been opened but before any RLS-protected
    query runs).

    Args:
        session: An active SQLAlchemy ``Session``.
        org_id:  The organization UUID to scope to (accepts UUID object or str).
    """
    session.execute(
        text("SET LOCAL app.current_org_id = :org_id"),
        {"org_id": str(org_id)},
    )
