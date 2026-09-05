"""enforce_billing_status_in_resolve_card_context

Revision ID: a54eb0cc672c
Revises: 939401fc98c9
Create Date: 2026-09-04 22:21:25.331292

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = 'a54eb0cc672c'
down_revision: Union[str, None] = '939401fc98c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.resolve_card_context(p_token TEXT)
        RETURNS TABLE (org_id UUID, stand_id UUID, default_branch TEXT, form_fields JSONB)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT
                o.id AS org_id,
                s.id AS stand_id,
                s.default_branch,
                fs.fields AS form_fields
            FROM cards c
            JOIN stands s ON c.stand_id = s.id
            JOIN organizations o ON s.org_id = o.id
            JOIN form_schemas fs ON o.id = fs.org_id
            WHERE c.token = p_token
              AND o.billing_status IN ('active', 'trialing');
        $$
    """)


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.resolve_card_context(p_token TEXT)
        RETURNS TABLE (org_id UUID, stand_id UUID, default_branch TEXT, form_fields JSONB)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT
                o.id AS org_id,
                s.id AS stand_id,
                s.default_branch,
                fs.fields AS form_fields
            FROM cards c
            JOIN stands s ON c.stand_id = s.id
            JOIN organizations o ON s.org_id = o.id
            JOIN form_schemas fs ON o.id = fs.org_id
            WHERE c.token = p_token;
        $$
    """)
