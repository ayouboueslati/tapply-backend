"""
app/models/organization.py
──────────────────────────
The top-level tenant entity.  Every other table with an ``org_id`` column
(or reachable via FK join) is RLS-scoped to a single organization.

RLS note:
  The ``organizations`` table itself is protected by ``FORCE ROW LEVEL
  SECURITY``.  The policy filters on ``id = current_setting(...)::uuid``, so
  a session can only see its own org row.  Cross-org admin access uses the
  ``tapply_admin`` PostgreSQL role (BYPASSRLS) from internal tooling — never
  from the application's connection pool (see README § Platform admin access).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        doc="UUID primary key generated server-side by gen_random_uuid().",
    )
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Human-readable display name for the organization.",
    )
    billing_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'active'"),
        doc="Billing state: 'active' | 'trialing' | 'past_due' | 'canceled'.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<Organization id={self.id} name={self.name!r}>"
