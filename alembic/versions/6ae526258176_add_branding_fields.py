"""add_branding_fields

Adds logo_url, theme_color, welcome_title and welcome_text columns to
the organizations table so each tenant can brand the public tap form
without requiring a manual DB migration.

Also updates auth.resolve_card_context to return the new branding fields.

Revision ID: 6ae526258176
Revises: e481bb755a94
Create Date: 2026-08-03 15:45:22.977034
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6ae526258176'
down_revision: Union[str, None] = 'e481bb755a94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('logo_url', sa.Text(), nullable=True))
    op.add_column('organizations', sa.Column(
        'theme_color', sa.Text(),
        server_default=sa.text("'#C9A96E'"),
        nullable=False,
    ))
    op.add_column('organizations', sa.Column(
        'welcome_title', sa.Text(),
        server_default=sa.text("'Choose Your Path'"),
        nullable=False,
    ))
    op.add_column('organizations', sa.Column(
        'welcome_text', sa.Text(),
        server_default=sa.text("'Find the programme that ignites your ambition.'"),
        nullable=False,
    ))

    # ── Update auth.resolve_card_context to return branding fields ────────────
    # Postgres cannot change a function's return type in-place — we must drop
    # the old signature first, then recreate with the extended columns.
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


def downgrade() -> None:
    # Revert resolve_card_context to the previous version (without branding fields)
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.resolve_card_context(p_token TEXT)
        RETURNS TABLE (
            org_id          UUID,
            stand_id        UUID,
            default_branch  TEXT,
            form_fields     JSONB,
            org_name        TEXT,
            branch_labels   JSONB
        )
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        AS $$
            SELECT
                o.id            AS org_id,
                s.id            AS stand_id,
                c.default_branch,
                fs.fields       AS form_fields,
                o.name          AS org_name,
                o.branch_labels
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

    op.drop_column('organizations', 'welcome_text')
    op.drop_column('organizations', 'welcome_title')
    op.drop_column('organizations', 'theme_color')
    op.drop_column('organizations', 'logo_url')
