"""
app/models/form_schema.py
─────────────────────────
Defines the fields that appear on the contact form linked to an organization's
stands.  Stored as JSONB for schema flexibility.

``fields`` shape (enforced at the application layer, not the DB):
    [
        {"name": "full_name",   "type": "text",   "required": true},
        {"name": "phone",       "type": "phone",  "required": true},
        {"name": "branch",      "type": "select", "options": ["Main", "North"]},
    ]
"""

import uuid

from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FormSchema(Base):
    __tablename__ = "form_schemas"

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
    fields: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        doc="JSON array of field descriptors. See module docstring for shape.",
    )

    def __repr__(self) -> str:
        return f"<FormSchema id={self.id} org_id={self.org_id}>"
