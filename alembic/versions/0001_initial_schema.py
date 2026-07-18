"""
alembic/versions/0001_initial_schema.py
────────────────────────────────────────
Initial Tapply schema: all 6 tables, Row-Level Security, and SECURITY DEFINER
bootstrap functions.

Revision: 0001
Down revision: None (first migration)

What this migration does
────────────────────────
1.  Enables the ``pgcrypto`` extension for ``gen_random_uuid()``.
2.  Creates the ``auth`` schema for privileged bootstrap functions.
3.  Creates all 6 tables in FK-dependency order:
        organizations → staff_users, stands
        stands        → cards
        organizations → form_schemas
        cards + organizations → submissions
4.  Enables and FORCES Row-Level Security on every table.
5.  Creates RLS policies scoped to ``app.current_org_id`` session variable:
        - Direct org_id tables: ``org_id = NULLIF(current_setting(...), '')::uuid``
        - ``cards``: join-based subquery through ``stands``
6.  Creates two SECURITY DEFINER functions in the ``auth`` schema.  These run
    as their creator (the migration superuser) and thus bypass FORCE RLS:
        auth.lookup_staff_org(email)        — resolves org for login bootstrap
        auth.create_organization(...)       — creates a new org + admin user
7.  Grants table-level privileges to ``tapply_app`` (EXCLUDING ``staff_users``).
    Grants EXECUTE on both auth functions to ``tapply_app``.
    The entire grants block is a no-op if ``tapply_app`` does not exist yet
    (safe to run before or after scripts/create_roles.sql).

Prerequisites
─────────────
- Run ``scripts/create_roles.sql`` to create the ``tapply_app`` role, then run
  this migration.  The migration does not create the role itself — role
  creation and credential management must not live inside a versioned migration.

RLS design notes
────────────────
- ``NULLIF(current_setting('app.current_org_id', true), '')::uuid``
  Handles two cases safely:
    • Setting not yet defined → current_setting returns NULL (missing_ok=true)
    • Setting is '' (empty) → NULLIF coerces to NULL
  In both cases the UUID cast produces NULL, and ``col = NULL`` is always
  FALSE under SQL NULL semantics → zero rows returned, no error raised.

- ``FORCE ROW LEVEL SECURITY`` applies the policies even to the table owner.
  Superusers (``postgres``) and roles with ``BYPASSRLS`` are still exempt.
  The SECURITY DEFINER functions work because their owner is the superuser
  who ran the migration.

- ``tapply_app`` has no SELECT on ``staff_users`` — direct queries raise
  ``ERROR: permission denied for table staff_users``.  All staff_users access
  goes through ``auth.lookup_staff_org`` (SECURITY DEFINER).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ── Revision metadata ─────────────────────────────────────────────────────────
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# ── Helper: the RLS expression used in every direct-org_id policy ─────────────
# Returns NULL (not '') when the GUC is unset or empty → no rows visible.
_ORG_SETTING = "NULLIF(current_setting('app.current_org_id', true), '')::uuid"


def upgrade() -> None:
    # ── 1. Extensions ─────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── 2. Auth schema ─────────────────────────────────────────────────────────
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    # ── 3. Tables (in FK-dependency order) ────────────────────────────────────

    # 3a. organizations — top-level tenant entity
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "billing_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 3b. staff_users — dashboard users, scoped to one org
    op.create_table(
        "staff_users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="uq_staff_users_email"),
    )
    op.create_index("ix_staff_users_org_id", "staff_users", ["org_id"])

    # 3c. stands — physical NFC/QR stands
    op.create_table(
        "stands",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("default_branch", sa.Text(), nullable=True),
    )
    op.create_index("ix_stands_org_id", "stands", ["org_id"])

    # 3d. cards — NFC/QR card attached to a stand (no direct org_id)
    op.create_table(
        "cards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "stand_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stands.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.Text(), nullable=False),
        sa.UniqueConstraint("token", name="uq_cards_token"),
    )
    op.create_index("ix_cards_stand_id", "cards", ["stand_id"])

    # 3e. form_schemas — JSONB field definitions per org
    op.create_table(
        "form_schemas",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_form_schemas_org_id", "form_schemas", ["org_id"])

    # 3f. submissions — customer contact form entries
    op.create_table(
        "submissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            comment=(
                "Denormalized for efficient RLS. "
                "Must equal cards.stand.org_id — enforced by application code."
            ),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'to_contact'"),
        ),
        sa.Column("branch", sa.Text(), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_submissions_org_id",  "submissions", ["org_id"])
    op.create_index("ix_submissions_card_id", "submissions", ["card_id"])

    # ── 4 & 5. Row-Level Security ──────────────────────────────────────────────
    #
    # ENABLE ROW LEVEL SECURITY: activates RLS for non-superuser access.
    # FORCE ROW LEVEL SECURITY:  also applies policies to the table owner
    #                             (superusers and BYPASSRLS roles still bypass).

    rls_tables = [
        "organizations",
        "staff_users",
        "stands",
        "cards",
        "form_schemas",
        "submissions",
    ]
    for tbl in rls_tables:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")

    # ── 5. Per-table RLS policies ──────────────────────────────────────────────
    #
    # Each policy covers ALL operations (SELECT, INSERT, UPDATE, DELETE).
    # USING   controls which rows are visible (SELECT / UPDATE / DELETE source).
    # WITH CHECK controls which rows can be written (INSERT / UPDATE target).
    # Both use the same expression so a session can only touch its own org.

    # organizations — filter on primary key (id = org context)
    op.execute(f"""
        CREATE POLICY organizations_isolation ON organizations
        FOR ALL
        USING      (id = {_ORG_SETTING})
        WITH CHECK (id = {_ORG_SETTING})
    """)

    # staff_users — direct org_id column
    op.execute(f"""
        CREATE POLICY staff_users_isolation ON staff_users
        FOR ALL
        USING      (org_id = {_ORG_SETTING})
        WITH CHECK (org_id = {_ORG_SETTING})
    """)

    # stands — direct org_id column
    op.execute(f"""
        CREATE POLICY stands_isolation ON stands
        FOR ALL
        USING      (org_id = {_ORG_SETTING})
        WITH CHECK (org_id = {_ORG_SETTING})
    """)

    # cards — no org_id; resolve via stands subquery
    op.execute(f"""
        CREATE POLICY cards_isolation ON cards
        FOR ALL
        USING (
            stand_id IN (
                SELECT id FROM stands
                WHERE org_id = {_ORG_SETTING}
            )
        )
        WITH CHECK (
            stand_id IN (
                SELECT id FROM stands
                WHERE org_id = {_ORG_SETTING}
            )
        )
    """)

    # form_schemas — direct org_id column
    op.execute(f"""
        CREATE POLICY form_schemas_isolation ON form_schemas
        FOR ALL
        USING      (org_id = {_ORG_SETTING})
        WITH CHECK (org_id = {_ORG_SETTING})
    """)

    # submissions — direct org_id column (denormalized for performance)
    op.execute(f"""
        CREATE POLICY submissions_isolation ON submissions
        FOR ALL
        USING      (org_id = {_ORG_SETTING})
        WITH CHECK (org_id = {_ORG_SETTING})
    """)

    # ── 6. SECURITY DEFINER bootstrap functions ───────────────────────────────
    #
    # These functions solve the RLS bootstrap problem: a session needs to know
    # the org_id BEFORE setting app.current_org_id, but the tables are protected.
    #
    # Solution: the functions run as their OWNER (the superuser who ran this
    # migration) and therefore bypass FORCE RLS.  The calling role (tapply_app)
    # only gets EXECUTE on these specific functions — no table-level privilege.
    #
    # Both functions use SET search_path = public to prevent search_path
    # injection attacks (a SECURITY DEFINER best practice).

    # auth.lookup_staff_org
    # ─────────────────────
    # Called at login time (Step 2) after Clerk verifies the user's identity.
    # Returns (user_id, org_id, role) so the app can call set_org_context().
    # No password handling — Clerk is the auth provider.
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.lookup_staff_org(p_email TEXT)
        RETURNS TABLE (user_id UUID, org_id UUID, role TEXT)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT id, org_id, role
            FROM   staff_users
            WHERE  email = p_email;
        $$
    """)

    # auth.create_organization
    # ────────────────────────
    # Called during org onboarding (Step 2).  tapply_app cannot INSERT into
    # organizations directly because FORCE RLS rejects inserts without a
    # pre-existing org context.  This function runs as the superuser owner,
    # performs both inserts atomically, and returns the new IDs.
    #
    # After calling this function, the application must call set_org_context()
    # with the returned org_id to scope subsequent queries.
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.create_organization(
            p_name           TEXT,
            p_billing_status TEXT DEFAULT 'active',
            p_admin_email    TEXT DEFAULT NULL,
            p_admin_role     TEXT DEFAULT 'owner'
        )
        RETURNS TABLE (org_id UUID, admin_user_id UUID)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            v_org_id  UUID;
            v_user_id UUID;
        BEGIN
            INSERT INTO organizations (name, billing_status)
            VALUES (p_name, p_billing_status)
            RETURNING id INTO v_org_id;

            IF p_admin_email IS NOT NULL THEN
                INSERT INTO staff_users (org_id, email, role)
                VALUES (v_org_id, p_admin_email, p_admin_role)
                RETURNING id INTO v_user_id;
            END IF;

            RETURN QUERY SELECT v_org_id, v_user_id;
        END;
        $$
    """)

    # ── 7. Grants to tapply_app ────────────────────────────────────────────────
    #
    # Wrapped in DO $$ ... $$ so the entire block is a no-op if tapply_app
    # does not exist yet.  Run scripts/create_roles.sql first, then re-run
    # `alembic upgrade head` (Alembic is idempotent for already-applied revs).
    #
    # Intentional omission: staff_users is NOT in the table grant list.
    # tapply_app must use auth.lookup_staff_org() to access staff data.
    # A direct SELECT on staff_users as tapply_app raises:
    #   ERROR: permission denied for table staff_users
    # This is verified by tests/test_rls.py::test_app_role_denied_direct_staff_users.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tapply_app') THEN

                -- Schema access
                GRANT USAGE ON SCHEMA public TO tapply_app;
                GRANT USAGE ON SCHEMA auth   TO tapply_app;

                -- Table access (staff_users intentionally excluded)
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON organizations, stands, cards, form_schemas, submissions
                    TO tapply_app;

                -- Sequence access (for any serial-based columns, future-proof)
                GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO tapply_app;

                -- Auth function access
                GRANT EXECUTE
                    ON FUNCTION auth.lookup_staff_org(text)
                    TO tapply_app;
                GRANT EXECUTE
                    ON FUNCTION auth.create_organization(text, text, text, text)
                    TO tapply_app;

                -- Revoke default PUBLIC access to privileged auth functions
                REVOKE EXECUTE
                    ON FUNCTION auth.lookup_staff_org(text)
                    FROM PUBLIC;
                REVOKE EXECUTE
                    ON FUNCTION auth.create_organization(text, text, text, text)
                    FROM PUBLIC;

            END IF;
        END
        $$
    """)


def downgrade() -> None:
    # ── 7. Revoke grants (best-effort; role may not exist) ────────────────────
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tapply_app') THEN
                REVOKE ALL ON organizations, stands, cards, form_schemas, submissions
                    FROM tapply_app;
                REVOKE USAGE ON SCHEMA public FROM tapply_app;
                REVOKE USAGE ON SCHEMA auth   FROM tapply_app;
            END IF;
        END
        $$
    """)

    # ── 6. Drop SECURITY DEFINER functions ────────────────────────────────────
    op.execute(
        "DROP FUNCTION IF EXISTS auth.create_organization(text, text, text, text)"
    )
    op.execute("DROP FUNCTION IF EXISTS auth.lookup_staff_org(text)")

    # ── 3. Drop tables (reverse FK-dependency order) ──────────────────────────
    # Policies and RLS settings are dropped automatically with the tables.
    op.drop_index("ix_submissions_card_id", table_name="submissions")
    op.drop_index("ix_submissions_org_id",  table_name="submissions")
    op.drop_table("submissions")

    op.drop_index("ix_form_schemas_org_id", table_name="form_schemas")
    op.drop_table("form_schemas")

    op.drop_index("ix_cards_stand_id", table_name="cards")
    op.drop_table("cards")

    op.drop_index("ix_stands_org_id", table_name="stands")
    op.drop_table("stands")

    op.drop_index("ix_staff_users_org_id", table_name="staff_users")
    op.drop_table("staff_users")

    op.drop_table("organizations")

    # ── 2. Drop auth schema (CASCADE removes any remaining objects) ───────────
    op.execute("DROP SCHEMA IF EXISTS auth CASCADE")

    # ── 1. Drop extension ─────────────────────────────────────────────────────
    # Commented out by default — pgcrypto may be used by other schemas.
    # Uncomment only if you are certain no other extension depends on it.
    # op.execute("DROP EXTENSION IF EXISTS pgcrypto")
