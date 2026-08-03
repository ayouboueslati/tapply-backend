"""
app/models/staff_user.py
────────────────────────
Staff members who log in to the Tapply dashboard.

Auth note (Step 2 — Clerk external auth):
  No password hash is stored here.  Clerk handles credential verification.
  After Clerk validates the user's identity (JWT), Tapply calls
  ``auth.lookup_staff_org(email)`` to resolve the org context before any
  RLS-protected query runs.

RLS note:
  ``tapply_app`` has NO direct SELECT privilege on this table.  All reads go
  through ``auth.lookup_staff_org()`` (SECURITY DEFINER).  This is the
  boundary tested by ``test_app_role_cannot_query_staff_users_directly``.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StaffUser(Base):
    __tablename__ = "staff_users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_staff_users_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Globally unique email address — used as the Clerk identity key.",
    )
    role: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Staff role: 'owner' | 'manager' | 'staff'.",
    )
    can_edit: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("false"),
        doc="If true, this staff member can update/delete submissions.",
    )
    can_edit_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="If set, can_edit auto-expires after this time. NULL means permanent.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<StaffUser id={self.id} email={self.email!r} role={self.role!r}>"
