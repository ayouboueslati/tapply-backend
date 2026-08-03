"""
tests/test_branch_labels.py
───────────────────────────
Tests for:
  GET  /organizations/me/branches
  PATCH /organizations/me/branches

Isolation: savepoint/rollback fixture — no test data persists.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.api.deps import get_db, get_clerk_email
from app.models.organization import Organization
from tests.conftest import _get_test_url

engine = create_engine(_get_test_url())
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def test_db_session():
    """
    Wraps each test in a transaction that is rolled back at teardown.
    ``create_savepoint`` lets the app call session.commit() internally
    without actually committing the outer transaction.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(
        bind=connection, join_transaction_mode="create_savepoint"
    )
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(test_db_session):
    def override_get_db():
        test_db_session.execute(text("SET ROLE tapply_app"))
        yield test_db_session
        test_db_session.execute(text("RESET ROLE"))

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    del app.dependency_overrides[get_db]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_org(session, org_name: str, email: str, role: str = "org_owner") -> uuid.UUID:
    """
    Creates an org + staff user via the SECURITY DEFINER function.
    Returns the org_id.
    """
    row = session.execute(
        text(
            "SELECT org_id, admin_user_id "
            "FROM auth.create_organization(:name, :status, :email, :role)"
        ),
        {"name": org_name, "status": "active", "email": email, "role": role},
    ).one()
    session.commit()
    return row.org_id


def _add_staff(session, org_id: uuid.UUID, email: str, role: str = "staff") -> None:
    """Directly inserts a staff_user row (superuser connection bypasses RLS)."""
    session.execute(
        text(
            "INSERT INTO staff_users (org_id, email, role) "
            "VALUES (:org_id, :email, :role)"
        ),
        {"org_id": org_id, "email": email, "role": role},
    )
    session.commit()


def _create_submission_with_branch(session, org_id: uuid.UUID, branch_val: str) -> None:
    """
    Inserts a submission with the given branch directly (superuser bypasses RLS).
    Creates a minimal stand + card + form_schema chain to satisfy FKs.
    """
    # form_schema
    session.execute(
        text("INSERT INTO form_schemas (org_id, fields) VALUES (:org_id, :fields)"),
        {"org_id": org_id, "fields": json.dumps([{"name": "email", "required": True}])},
    )
    # stand
    row = session.execute(
        text(
            "INSERT INTO stands (org_id, name) VALUES (:org_id, 'Test Stand') RETURNING id"
        ),
        {"org_id": org_id},
    ).one()
    stand_id = row.id
    # card
    token = str(uuid.uuid4())
    row = session.execute(
        text(
            "INSERT INTO cards (stand_id, token) VALUES (:stand_id, :token) RETURNING id"
        ),
        {"stand_id": stand_id, "token": token},
    ).one()
    card_id = row.id
    # submission
    session.execute(
        text(
            "INSERT INTO submissions (card_id, org_id, branch, data) "
            "VALUES (:card_id, :org_id, :branch, :data)"
        ),
        {
            "card_id": card_id,
            "org_id": org_id,
            "branch": branch_val,
            "data": json.dumps({"email": "x@example.com"}),
        },
    )
    session.commit()


HEADERS = {"Authorization": "Bearer dummy"}


# ── GET /organizations/me/branches ───────────────────────────────────────

class TestGetBranchLabels:
    def test_returns_default_labels_as_list(self, client, test_db_session):
        """
        A freshly created org must return the default label list []
        and it must be a JSON array (Python list), not a bare string.
        """
        _create_org(test_db_session, "Org A", "owner@a.com")
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.get("/organizations/me/branches", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["branch_labels"], list), (
            "branch_labels must be a list, not a raw string"
        )
        assert data["branch_labels"] == []

        del app.dependency_overrides[get_clerk_email]

    def test_orm_returns_python_list(self, test_db_session):
        """
        Confirm the ORM maps branch_labels to a Python list directly,
        not a JSON string requiring a second parse step.
        """
        org_id = _create_org(test_db_session, "Org B", "owner@b.com")
        # Fetch via ORM as superuser (no RLS context needed)
        org = test_db_session.get(Organization, org_id)
        assert isinstance(org.branch_labels, list), (
            "ORM must deserialise branch_labels as list, got: "
            f"{type(org.branch_labels).__name__}"
        )
        assert org.branch_labels == []


# ── PATCH /organizations/me/branches ─────────────────────────────────────

class TestPatchBranchLabels:

    # ── Input validation ──────────────────────────────────────────────────────

    def test_empty_list_rejected(self, client, test_db_session):
        _create_org(test_db_session, "Org A", "owner@a.com")
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.patch(
            "/organizations/me/branches",
            json={"branch_labels": []},
            headers=HEADERS,
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

        del app.dependency_overrides[get_clerk_email]

    def test_duplicate_labels_rejected(self, client, test_db_session):
        _create_org(test_db_session, "Org A", "owner@a.com")
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.patch(
            "/organizations/me/branches",
            json={"branch_labels": ["new", "new"]},
            headers=HEADERS,
        )
        assert resp.status_code == 400
        assert "duplicate" in resp.json()["detail"].lower()

        del app.dependency_overrides[get_clerk_email]

    def test_label_exceeding_50_chars_rejected(self, client, test_db_session):
        _create_org(test_db_session, "Org A", "owner@a.com")
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        long_label = "x" * 51
        resp = client.patch(
            "/organizations/me/branches",
            json={"branch_labels": ["valid", long_label]},
            headers=HEADERS,
        )
        assert resp.status_code == 400
        assert "50" in resp.json()["detail"]

        del app.dependency_overrides[get_clerk_email]

    # ── Role check ────────────────────────────────────────────────────────────

    def test_regular_staff_cannot_update_labels(self, client, test_db_session):
        """Non-owner staff must receive 403."""
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        _add_staff(test_db_session, org_id, "staff@a.com", role="staff")
        app.dependency_overrides[get_clerk_email] = lambda: "staff@a.com"

        resp = client.patch(
            "/organizations/me/branches",
            json={"branch_labels": ["new_label"]},
            headers=HEADERS,
        )
        assert resp.status_code == 403

        del app.dependency_overrides[get_clerk_email]

    def test_org_owner_can_update_labels(self, client, test_db_session):
        """org_owner must succeed when input is valid and no labels are in use."""
        _create_org(test_db_session, "Org A", "owner@a.com")
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.patch(
            "/organizations/me/branches",
            json={"branch_labels": ["london", "new_york"]},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["branch_labels"] == ["london", "new_york"]

        del app.dependency_overrides[get_clerk_email]

    # ── Orphan protection ─────────────────────────────────────────────────────

    def test_removing_in_use_label_rejected(self, client, test_db_session):
        """
        Removing a label that is currently referenced by a submission must
        result in 409.
        """
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        
        # Set custom labels ["london", "new_york"]
        test_db_session.execute(
            text(
                "UPDATE organizations SET branch_labels = :labels WHERE id = :org_id"
            ),
            {"labels": json.dumps(["london", "new_york"]), "org_id": org_id},
        )
        test_db_session.commit()
        
        _create_submission_with_branch(test_db_session, org_id, "london")
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        # Try to remove "london" (which has a submission)
        resp = client.patch(
            "/organizations/me/branches",
            json={"branch_labels": ["new_york"]},
            headers=HEADERS,
        )
        assert resp.status_code == 409
        assert "london" in resp.json()["detail"]

        del app.dependency_overrides[get_clerk_email]

    def test_atomic_rejection_add_and_remove_in_use(self, client, test_db_session):
        """
        A request that both adds a new label AND removes an in-use label must
        be rejected entirely — the labels must be unchanged after the call.
        """
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        
        # Set custom labels ["london", "new_york"]
        test_db_session.execute(
            text(
                "UPDATE organizations SET branch_labels = :labels WHERE id = :org_id"
            ),
            {"labels": json.dumps(["london", "new_york"]), "org_id": org_id},
        )
        test_db_session.commit()
        
        _create_submission_with_branch(test_db_session, org_id, "london")
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        # Add "tokyo", remove "london" (in use) — should reject
        resp = client.patch(
            "/organizations/me/branches",
            json={"branch_labels": ["new_york", "tokyo"]},
            headers=HEADERS,
        )
        assert resp.status_code == 409

        # Labels must be unchanged
        get_resp = client.get("/organizations/me/branches", headers=HEADERS)
        assert get_resp.json()["branch_labels"] == ["london", "new_york"]

        del app.dependency_overrides[get_clerk_email]

    def test_remove_unused_label_succeeds_and_untouched_submissions_intact(
        self, client, test_db_session
    ):
        """
        Labels [A, B, C] — only A and C have submissions — remove B, add D.
        Result must be [A, C, D].  Submissions with branch A and C must be
        completely untouched (not modified, not deleted).
        """
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")

        # Set custom labels [A, B, C] directly in the DB (bypassing RLS as superuser)
        test_db_session.execute(
            text(
                "UPDATE organizations SET branch_labels = :labels WHERE id = :org_id"
            ),
            {"labels": json.dumps(["A", "B", "C"]), "org_id": org_id},
        )
        test_db_session.commit()

        # Create submissions using A and C (not B)
        _create_submission_with_branch(test_db_session, org_id, "A")
        _create_submission_with_branch(test_db_session, org_id, "C")

        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        # PATCH: remove B, add D → new list [A, C, D]
        resp = client.patch(
            "/organizations/me/branches",
            json={"branch_labels": ["A", "C", "D"]},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["branch_labels"] == ["A", "C", "D"]

        # Verify submissions with A and C are untouched
        rows = test_db_session.execute(
            text("SELECT branch FROM submissions WHERE org_id = :org_id ORDER BY branch"),
            {"org_id": org_id},
        ).fetchall()
        branches = [r.branch for r in rows]
        assert branches == ["A", "C"], (
            f"Expected submissions with branch [A, C] to be untouched, got: {branches}"
        )

        del app.dependency_overrides[get_clerk_email]
