"""
alembic/versions/0004_add_org_name_to_card_context.py
────────────────────────────────────────────────────
Adds org_name to auth.resolve_card_context

Revision: 0004
Down revision: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

def upgrade() -> None:
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

def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth.resolve_card_context(text)")
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
