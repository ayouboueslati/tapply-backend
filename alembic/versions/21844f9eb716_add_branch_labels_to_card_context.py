"""add branch labels to card context

Revision ID: 21844f9eb716
Revises: 82fe1c0c0482
Create Date: 2026-07-30 15:43:52.426848

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '21844f9eb716'
down_revision: Union[str, None] = '82fe1c0c0482'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth.resolve_card_context(text)")
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.resolve_card_context(p_token TEXT)
        RETURNS TABLE (org_id UUID, stand_id UUID, default_branch TEXT, form_fields JSONB, org_name TEXT, branch_labels JSONB)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT
                o.id AS org_id,
                s.id AS stand_id,
                s.default_branch,
                fs.fields AS form_fields,
                o.name AS org_name,
                o.branch_labels AS branch_labels
            FROM cards c
            JOIN stands s ON c.stand_id = s.id
            JOIN organizations o ON s.org_id = o.id
            JOIN form_schemas fs ON o.id = fs.org_id
            WHERE c.token = p_token;
        $$
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tapply_app') THEN
                GRANT EXECUTE ON FUNCTION auth.resolve_card_context(text) TO tapply_app;
                REVOKE EXECUTE ON FUNCTION auth.resolve_card_context(text) FROM PUBLIC;
            END IF;
        END
        $$
    """)

def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth.resolve_card_context(text)")
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.resolve_card_context(p_token TEXT)
        RETURNS TABLE (org_id UUID, stand_id UUID, default_branch TEXT, form_fields JSONB, org_name TEXT)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT
                o.id AS org_id,
                s.id AS stand_id,
                s.default_branch,
                fs.fields AS form_fields,
                o.name AS org_name
            FROM cards c
            JOIN stands s ON c.stand_id = s.id
            JOIN organizations o ON s.org_id = o.id
            JOIN form_schemas fs ON o.id = fs.org_id
            WHERE c.token = p_token;
        $$
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tapply_app') THEN
                GRANT EXECUTE ON FUNCTION auth.resolve_card_context(text) TO tapply_app;
                REVOKE EXECUTE ON FUNCTION auth.resolve_card_context(text) FROM PUBLIC;
            END IF;
        END
        $$
    """)

