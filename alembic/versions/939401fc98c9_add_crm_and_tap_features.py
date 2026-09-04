"""add_crm_and_tap_features

Revision ID: 939401fc98c9
Revises: 6ae526258176
Create Date: 2026-08-13 12:00:52.217621

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '939401fc98c9'
down_revision: Union[str, None] = '6ae526258176'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    # organizations
    op.add_column('organizations', sa.Column('retention_days', sa.Integer(), server_default=sa.text('365'), nullable=False))

    # cards
    op.add_column('cards', sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('cards', sa.Column('assigned_recruiter_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_cards_assigned_recruiter', 'cards', 'staff_users', ['assigned_recruiter_id'], ['id'], ondelete='SET NULL')

    # submissions
    op.add_column('submissions', sa.Column('assigned_to', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_submissions_assigned_to', 'submissions', 'staff_users', ['assigned_to'], ['id'], ondelete='SET NULL')
    op.add_column('submissions', sa.Column('score', sa.Integer(), nullable=True))
    op.add_column('submissions', sa.Column('notes', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('submissions', sa.Column('is_duplicate', sa.Boolean(), server_default=sa.text('false'), nullable=False))

    # Update auth.resolve_card_context to return is_active and assigned_recruiter_id
    op.execute("DROP FUNCTION IF EXISTS auth.resolve_card_context(text)")
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.resolve_card_context(p_token TEXT)
        RETURNS TABLE (
            org_id          UUID,
            stand_id        UUID,
            default_branch  TEXT,
            form_fields     JSONB,
            org_name        TEXT,
            branch_labels   JSONB,
            logo_url        TEXT,
            theme_color     TEXT,
            welcome_title   TEXT,
            welcome_text    TEXT,
            is_active       BOOLEAN,
            assigned_recruiter_id UUID
        )
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        AS $$
            SELECT
                o.id            AS org_id,
                s.id            AS stand_id,
                s.default_branch,
                fs.fields       AS form_fields,
                o.name          AS org_name,
                o.branch_labels,
                o.logo_url,
                o.theme_color,
                o.welcome_title,
                o.welcome_text,
                c.is_active,
                c.assigned_recruiter_id
            FROM  cards        c
            JOIN  stands       s  ON s.id = c.stand_id
            JOIN  organizations o  ON o.id = s.org_id
            LEFT JOIN form_schemas fs ON fs.org_id = o.id
            WHERE c.token = p_token
            LIMIT 1;
        $$;

        GRANT EXECUTE ON FUNCTION auth.resolve_card_context(text) TO tapply_app;
        REVOKE EXECUTE ON FUNCTION auth.resolve_card_context(text) FROM PUBLIC;
    """)

def downgrade() -> None:
    # Revert resolve_card_context
    op.execute("DROP FUNCTION IF EXISTS auth.resolve_card_context(text)")
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.resolve_card_context(p_token TEXT)
        RETURNS TABLE (
            org_id          UUID,
            stand_id        UUID,
            default_branch  TEXT,
            form_fields     JSONB,
            org_name        TEXT,
            branch_labels   JSONB,
            logo_url        TEXT,
            theme_color     TEXT,
            welcome_title   TEXT,
            welcome_text    TEXT
        )
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        AS $$
            SELECT
                o.id            AS org_id,
                s.id            AS stand_id,
                s.default_branch,
                fs.fields       AS form_fields,
                o.name          AS org_name,
                o.branch_labels,
                o.logo_url,
                o.theme_color,
                o.welcome_title,
                o.welcome_text
            FROM  cards        c
            JOIN  stands       s  ON s.id = c.stand_id
            JOIN  organizations o  ON o.id = s.org_id
            LEFT JOIN form_schemas fs ON fs.org_id = o.id
            WHERE c.token = p_token
            LIMIT 1;
        $$;

        GRANT EXECUTE ON FUNCTION auth.resolve_card_context(text) TO tapply_app;
        REVOKE EXECUTE ON FUNCTION auth.resolve_card_context(text) FROM PUBLIC;
    """)

    # submissions
    op.drop_column('submissions', 'is_duplicate')
    op.drop_column('submissions', 'notes')
    op.drop_column('submissions', 'score')
    op.drop_constraint('fk_submissions_assigned_to', 'submissions', type_='foreignkey')
    op.drop_column('submissions', 'assigned_to')

    # cards
    op.drop_constraint('fk_cards_assigned_recruiter', 'cards', type_='foreignkey')
    op.drop_column('cards', 'assigned_recruiter_id')
    op.drop_column('cards', 'is_active')

    # organizations
    op.drop_column('organizations', 'retention_days')
