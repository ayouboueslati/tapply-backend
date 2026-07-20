"""
alembic/versions/0003_status_labels.py
───────────────────────────────────────
Adds ``status_labels`` JSONB column to ``organizations``.

Revision: 0003
Down revision: 0002

What this migration does
────────────────────────
1.  Adds ``status_labels JSONB NOT NULL DEFAULT '["to_contact","contacted"]'::jsonb``
    to the ``organizations`` table.

    - The ``::jsonb`` cast is explicit so PostgreSQL stores this as a real JSONB
      value (not a bare text string). Omitting the cast would still work (Postgres
      coerces the text literal automatically), but explicit casting is correct
      practice and removes any ambiguity about the stored type.

    - ``ALTER TABLE … ADD COLUMN … DEFAULT`` backfills all existing rows atomically
      before the NOT NULL constraint is enforced — no separate UPDATE is required.

    - The two-value default ``["to_contact", "contacted"]`` is intentional: it
      keeps Step 3's hardcoded ``'to_contact'`` initial submission status
      meaningful.  Every org — new or existing — starts with at least one valid
      label that matches the default status already in use by submissions.

2.  No new grants are needed: ``tapply_app`` already holds
    ``SELECT, INSERT, UPDATE, DELETE`` on ``organizations`` from migration 0001.

``downgrade()`` drops the column (idempotently, using ``IF EXISTS``).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ── Revision metadata ─────────────────────────────────────────────────────────
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "status_labels",
            postgresql.JSONB(),
            nullable=False,
            # Explicit ::jsonb cast — stores a real JSONB array, not text.
            server_default=sa.text("'[\"to_contact\",\"contacted\"]'::jsonb"),
            doc=(
                "Ordered list of valid submission status labels for this org. "
                "Managed exclusively through the /organizations/me/status-labels "
                "endpoint (org_owner role only). "
                "Default: ['to_contact', 'contacted']."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "status_labels")
