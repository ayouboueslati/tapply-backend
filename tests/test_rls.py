"""
tests/test_rls.py
─────────────────
Row-Level Security and privilege-boundary tests for Tapply.

Test inventory
──────────────
1. test_org_isolation
   Proves that a session scoped to Org A cannot see Org B's submissions
   (and vice versa) even when the SELECT has no WHERE clause.

2. test_lookup_staff_org_bypasses_rls
   Proves that auth.lookup_staff_org() returns a staff user row without
   requiring app.current_org_id to be set first — validating the login
   bootstrap path.

3. test_create_organization_bypasses_rls
   Proves that auth.create_organization() can INSERT a new org + admin user
   without a pre-existing org context — validating the onboarding path.
   Also verifies the org row becomes visible once context is set.

4. test_app_role_denied_direct_staff_users
   Proves that tapply_app is denied SELECT on staff_users at the GRANT level
   (not just by RLS).  A direct query raises InsufficientPrivilege, not empty
   rows.  This validates Option B's core security claim: the app role cannot
   reach staff_users even if it "forgets" to set the org context.
   Skipped if tapply_app role does not exist (run scripts/create_roles.sql).

Test isolation
──────────────
All tests use the `owner_conn` fixture (superuser connection, autocommit=OFF).
Every test runs inside a single transaction that is rolled back at teardown.
No test data persists between runs.

For tests that switch to the tapply_app role, we use:
    cur.execute("SET ROLE tapply_app")
    ...
    cur.execute("RESET ROLE")
This avoids needing tapply_app's password; the superuser can SET ROLE to any
role it has been granted or to any role at all (superuser privilege).

Note on psycopg2 error state:
After an expected exception (e.g. InsufficientPrivilege), the connection is in
aborted state.  The fixture teardown calls conn.rollback() which resets it.
For tests that need to do work AFTER catching an expected error, call
conn.rollback() inside the test before proceeding.
"""

import secrets

import psycopg2
import psycopg2.errors
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Org isolation
# ─────────────────────────────────────────────────────────────────────────────


def test_org_isolation(owner_conn):
    """
    A session scoped to Org A cannot see Org B's submissions, even with a
    SELECT * FROM submissions that has no WHERE clause.

    Setup (as superuser, bypasses FORCE RLS):
      - Insert two organizations directly.
      - Build the minimal object graph: org → stand → card → submission.

    Verification (as tapply_app via SET ROLE):
      - Set app.current_org_id = org_a_id, SELECT * FROM submissions.
        → Must return exactly 1 row belonging to Org A.
      - Reset context, set app.current_org_id = org_b_id, SELECT again.
        → Must return exactly 1 row belonging to Org B.
    """
    cur = owner_conn.cursor()

    # ── Setup: two orgs ───────────────────────────────────────────────────────
    cur.execute(
        "INSERT INTO organizations (name, billing_status) VALUES (%s, %s) RETURNING id",
        ("Org A", "active"),
    )
    org_a_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO organizations (name, billing_status) VALUES (%s, %s) RETURNING id",
        ("Org B", "active"),
    )
    org_b_id = cur.fetchone()[0]

    # ── Setup: stands ─────────────────────────────────────────────────────────
    cur.execute(
        "INSERT INTO stands (org_id, name) VALUES (%s, %s) RETURNING id",
        (org_a_id, "Stand A"),
    )
    stand_a_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO stands (org_id, name) VALUES (%s, %s) RETURNING id",
        (org_b_id, "Stand B"),
    )
    stand_b_id = cur.fetchone()[0]

    # ── Setup: cards (token must be unique and non-sequential) ────────────────
    token_a = secrets.token_urlsafe(16)
    token_b = secrets.token_urlsafe(16)

    cur.execute(
        "INSERT INTO cards (stand_id, token) VALUES (%s, %s) RETURNING id",
        (stand_a_id, token_a),
    )
    card_a_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO cards (stand_id, token) VALUES (%s, %s) RETURNING id",
        (stand_b_id, token_b),
    )
    card_b_id = cur.fetchone()[0]

    # ── Setup: one submission per org ─────────────────────────────────────────
    cur.execute(
        "INSERT INTO submissions (card_id, org_id, data) VALUES (%s, %s, %s::jsonb) RETURNING id",
        (card_a_id, org_a_id, '{"source": "org_a"}'),
    )
    sub_a_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO submissions (card_id, org_id, data) VALUES (%s, %s, %s::jsonb) RETURNING id",
        (card_b_id, org_b_id, '{"source": "org_b"}'),
    )
    sub_b_id = cur.fetchone()[0]

    # ── Verify: scoped to Org A ───────────────────────────────────────────────
    # SET ROLE tapply_app — connection now acts with tapply_app's privileges.
    # SET LOCAL app.current_org_id — RLS context scoped to this transaction.
    cur.execute("SET ROLE tapply_app")
    cur.execute("SET LOCAL app.current_org_id = %s", (str(org_a_id),))

    cur.execute("SELECT id, org_id FROM submissions")  # ← NO WHERE clause
    rows_a = cur.fetchall()

    cur.execute("RESET ROLE")

    assert len(rows_a) == 1, (
        f"Expected exactly 1 submission visible to Org A session, got {len(rows_a)}. "
        f"RLS policy may not be enforced."
    )
    visible_sub_id, visible_org_id = rows_a[0]
    assert str(visible_sub_id) == str(sub_a_id), "Wrong submission returned for Org A."
    assert str(visible_org_id) == str(org_a_id), "Visible row belongs to wrong org."

    # ── Verify: scoped to Org B ───────────────────────────────────────────────
    cur.execute("SET ROLE tapply_app")
    cur.execute("SET LOCAL app.current_org_id = %s", (str(org_b_id),))

    cur.execute("SELECT id, org_id FROM submissions")  # ← NO WHERE clause
    rows_b = cur.fetchall()

    cur.execute("RESET ROLE")

    assert len(rows_b) == 1, (
        f"Expected exactly 1 submission visible to Org B session, got {len(rows_b)}."
    )
    visible_sub_id, visible_org_id = rows_b[0]
    assert str(visible_sub_id) == str(sub_b_id), "Wrong submission returned for Org B."
    assert str(visible_org_id) == str(org_b_id), "Visible row belongs to wrong org."


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — auth.lookup_staff_org bypasses RLS
# ─────────────────────────────────────────────────────────────────────────────


def test_lookup_staff_org_bypasses_rls(owner_conn, tapply_app_exists):
    """
    auth.lookup_staff_org(email) returns the correct (user_id, org_id, role)
    tuple even when app.current_org_id has NOT been set in the session.

    This validates the login bootstrap path: Clerk verifies the user's identity
    externally, then the app calls this function to resolve the org context
    before issuing any further RLS-protected queries.
    """
    if not tapply_app_exists:
        pytest.skip("tapply_app role not found — run scripts/create_roles.sql first.")

    cur = owner_conn.cursor()

    # Setup: insert staff user directly as superuser (bypasses RLS).
    cur.execute(
        "INSERT INTO organizations (name, billing_status) VALUES (%s, %s) RETURNING id",
        ("Bootstrap Org", "active"),
    )
    org_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO staff_users (org_id, email, role) VALUES (%s, %s, %s) RETURNING id",
        (org_id, "bootstrap@example.com", "owner"),
    )
    expected_user_id = cur.fetchone()[0]

    # Verify: call the function AS tapply_app with NO org context set.
    cur.execute("SET ROLE tapply_app")
    # Deliberately do NOT set app.current_org_id — this is the bootstrap case.
    cur.execute(
        "SELECT user_id, org_id, role FROM auth.lookup_staff_org(%s)",
        ("bootstrap@example.com",),
    )
    row = cur.fetchone()
    cur.execute("RESET ROLE")

    assert row is not None, (
        "auth.lookup_staff_org returned no row. "
        "SECURITY DEFINER may not be bypassing RLS correctly."
    )
    returned_user_id, returned_org_id, returned_role = row
    assert str(returned_user_id) == str(expected_user_id)
    assert str(returned_org_id) == str(org_id)
    assert returned_role == "owner"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — auth.create_organization bypasses RLS
# ─────────────────────────────────────────────────────────────────────────────


def test_create_organization_bypasses_rls(owner_conn, tapply_app_exists):
    """
    auth.create_organization() inserts a new org + founding admin user without
    a pre-existing org context — validating the onboarding bootstrap path.

    FORCE ROW LEVEL SECURITY on `organizations` would reject a direct INSERT
    from tapply_app (the WITH CHECK policy fails when no context is set).
    The SECURITY DEFINER function runs as the superuser owner and bypasses this.

    After creation, we verify the org row is visible once the context is set.
    """
    if not tapply_app_exists:
        pytest.skip("tapply_app role not found — run scripts/create_roles.sql first.")

    cur = owner_conn.cursor()

    # Call create_organization AS tapply_app with NO context set.
    cur.execute("SET ROLE tapply_app")
    cur.execute(
        "SELECT org_id, admin_user_id "
        "FROM auth.create_organization(%s, %s, %s, %s)",
        ("Onboarding Org", "active", "owner@onboarding.com", "owner"),
    )
    row = cur.fetchone()
    new_org_id, new_admin_id = row
    cur.execute("RESET ROLE")

    assert new_org_id is not None, "create_organization did not return an org_id."
    assert new_admin_id is not None, "create_organization did not return an admin_user_id."

    # Now set context and verify the org row is visible through RLS.
    cur.execute("SET ROLE tapply_app")
    cur.execute("SET LOCAL app.current_org_id = %s", (str(new_org_id),))
    cur.execute("SELECT id, name FROM organizations")
    org_rows = cur.fetchall()
    cur.execute("RESET ROLE")

    assert len(org_rows) == 1, (
        f"Expected 1 org row after setting context to new org, got {len(org_rows)}."
    )
    assert str(org_rows[0][0]) == str(new_org_id)
    assert org_rows[0][1] == "Onboarding Org"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — tapply_app is denied direct access to staff_users
# ─────────────────────────────────────────────────────────────────────────────


def test_app_role_denied_direct_staff_users(owner_conn, tapply_app_exists):
    """
    tapply_app receives ``ERROR: permission denied for table staff_users`` when
    attempting a direct SELECT — it is NOT silently returned empty rows.

    This is the critical distinction between Option B (SECURITY DEFINER) and
    Option C (null-context RLS exception):

      - Empty rows  → RLS is the only guard.  A missing SET LOCAL = silent leak.
      - Permission denied → GRANT is the first wall.  RLS is a second layer.
                            A missing SET LOCAL = still denied.

    If this test fails with zero rows instead of an exception, it means
    tapply_app was accidentally granted SELECT on staff_users and the privilege
    boundary no longer exists.

    Skipped if tapply_app role does not exist (run scripts/create_roles.sql).
    """
    if not tapply_app_exists:
        pytest.skip("tapply_app role not found — run scripts/create_roles.sql first.")

    cur = owner_conn.cursor()
    cur.execute("SET ROLE tapply_app")

    with pytest.raises(psycopg2.errors.InsufficientPrivilege) as exc_info:
        # No org context set, no WHERE clause — this must FAIL, not return [].
        cur.execute("SELECT * FROM staff_users")

    # Verify the error targets the right table (not just a schema permission).
    assert "staff_users" in str(exc_info.value).lower(), (
        f"Expected 'staff_users' in error message, got: {exc_info.value}"
    )
    # Connection is now in aborted state; teardown rollback handles cleanup.
