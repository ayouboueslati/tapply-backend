"""
alembic/versions/0002_resolve_card_context.py
─────────────────────────────────────────────
Adds auth.resolve_card_context

Revision: 0002
Down revision: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # TODO: organizations.billing_status is NOT checked. A suspended/inactive
    # organization's card will still resolve and accept submissions. This is
    # deferred until the billing model is finalized.
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


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth.resolve_card_context(text)")
