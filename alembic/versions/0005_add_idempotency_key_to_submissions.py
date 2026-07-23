"""
alembic/versions/0005_add_idempotency_key_to_submissions.py
──────────────────────────────────────────────────────────
Adds idempotency_key to submissions with UNIQUE constraint.

Revision: 0005
Down revision: 0004
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('submissions', sa.Column('idempotency_key', sa.UUID(as_uuid=True), nullable=True))
    op.create_unique_constraint('uq_submissions_org_id_idempotency_key', 'submissions', ['org_id', 'idempotency_key'])

def downgrade() -> None:
    op.drop_constraint('uq_submissions_org_id_idempotency_key', 'submissions', type_='unique')
    op.drop_column('submissions', 'idempotency_key')
