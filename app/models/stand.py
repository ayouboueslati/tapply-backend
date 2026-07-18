"""
app/models/stand.py
───────────────────
A physical NFC/QR stand belonging to an organization.

Each stand optionally has a default_branch — the physical location or queue
branch that new submissions are routed to when no branch is specified on the
card scan.
"""

import uuid

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Stand(Base):
    __tablename__ = "stands"

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
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Human-readable label for the stand (e.g. 'Reception desk').",
    )
    default_branch: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Default routing branch for this stand. NULL means no default.",
    )

    def __repr__(self) -> str:
        return f"<Stand id={self.id} name={self.name!r}>"
