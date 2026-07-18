"""
app/models/submission.py
────────────────────────
A contact form submission created when a customer taps/scans a card.

``org_id`` is stored directly (denormalized from ``cards → stands → org_id``)
to make the RLS policy a simple column comparison rather than a two-level join.
The FK from ``card_id → cards → stands → org_id`` is the authoritative path;
the direct ``org_id`` column is a performance optimization and must be kept
consistent at the application layer.

``status`` lifecycle:
    'to_contact'  →  'contacted'  →  'closed'
                  ↘  'no_answer'  →  'contacted'  →  'closed'
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc=(
            "Denormalized org reference for efficient RLS policy evaluation. "
            "Must equal cards.stand.org_id — enforced by application code."
        ),
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'to_contact'"),
        doc="Workflow status: 'to_contact' | 'no_answer' | 'contacted' | 'closed'.",
    )
    branch: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Routing branch captured at scan time. NULL means stand default applies.",
    )
    data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        doc="Customer-submitted form payload matching the org's FormSchema.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<Submission id={self.id} org_id={self.org_id} status={self.status!r}>"
        )
