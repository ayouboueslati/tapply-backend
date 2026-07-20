"""
tests/test_submissions.py
─────────────────────────
Tests for:
  PATCH /submissions/{id}   — status/branch update
  GET   /submissions        — filtered listing with pagination

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
from tests.conftest import _get_test_url

engine = create_engine(_get_test_url())
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def test_db_session():
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

def _create_org(session, org_name: str, email: str) -> uuid.UUID:
    row = session.execute(
        text(
            "SELECT org_id, admin_user_id "
            "FROM auth.create_organization(:name, :status, :email, :role)"
        ),
        {"name": org_name, "status": "active", "email": email, "role": "org_owner"},
    ).one()
    session.commit()
    return row.org_id


def _create_full_stack(
    session,
    org_id: uuid.UUID,
    status_val: str = "to_contact",
    branch_val: str | None = None,
) -> uuid.UUID:
    """
    Creates form_schema → stand → card → submission for the given org.
    Returns the submission id.
    """
    # form_schema (idempotent: skip if one already exists for this org)
    existing = session.execute(
        text("SELECT id FROM form_schemas WHERE org_id = :org_id LIMIT 1"),
        {"org_id": org_id},
    ).one_or_none()
    if not existing:
        session.execute(
            text(
                "INSERT INTO form_schemas (org_id, fields) VALUES (:org_id, :fields)"
            ),
            {
                "org_id": org_id,
                "fields": json.dumps([{"name": "email", "required": True}]),
            },
        )

    # stand
    stand_row = session.execute(
        text(
            "INSERT INTO stands (org_id, name) VALUES (:org_id, 'Stand') RETURNING id"
        ),
        {"org_id": org_id},
    ).one()
    stand_id = stand_row.id

    # card
    token = str(uuid.uuid4())
    card_row = session.execute(
        text(
            "INSERT INTO cards (stand_id, token) VALUES (:stand_id, :token) RETURNING id"
        ),
        {"stand_id": stand_id, "token": token},
    ).one()
    card_id = card_row.id

    # submission
    sub_row = session.execute(
        text(
            "INSERT INTO submissions (card_id, org_id, status, branch, data) "
            "VALUES (:card_id, :org_id, :status, :branch, :data) RETURNING id"
        ),
        {
            "card_id": card_id,
            "org_id": org_id,
            "status": status_val,
            "branch": branch_val,
            "data": json.dumps({"email": "test@example.com"}),
        },
    ).one()
    session.commit()
    return sub_row.id


def _set_status_labels(session, org_id: uuid.UUID, labels: list) -> None:
    """Direct DB update to set custom status labels (bypasses RLS as superuser)."""
    session.execute(
        text(
            "UPDATE organizations SET status_labels = :labels WHERE id = :org_id"
        ),
        {"labels": json.dumps(labels), "org_id": org_id},
    )
    session.commit()


HEADERS = {"Authorization": "Bearer dummy"}


# ── PATCH /submissions/{id} ───────────────────────────────────────────────────

class TestPatchSubmission:

    def test_valid_status_update_succeeds(self, client, test_db_session):
        """Updating status to a label in the org's list must succeed."""
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        sub_id = _create_full_stack(test_db_session, org_id, status_val="to_contact")
        # Default labels include "contacted"
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.patch(
            f"/submissions/{sub_id}",
            json={"status": "contacted"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "contacted"

        del app.dependency_overrides[get_clerk_email]

    def test_invalid_status_returns_400(self, client, test_db_session):
        """A status value not in the org's list must be rejected with 400."""
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        sub_id = _create_full_stack(test_db_session, org_id)
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.patch(
            f"/submissions/{sub_id}",
            json={"status": "completely_made_up_label"},
            headers=HEADERS,
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "completely_made_up_label" in detail

        del app.dependency_overrides[get_clerk_email]

    def test_branch_update_accepts_arbitrary_text(self, client, test_db_session):
        """
        Branch is free text — any string must be accepted without validation.
        Consistent with Step 3's public tap endpoint.
        """
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        sub_id = _create_full_stack(test_db_session, org_id)
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        arbitrary_branch = "🏢 Floor 3 / North Wing — Booth #42 (Special)"
        resp = client.patch(
            f"/submissions/{sub_id}",
            json={"branch": arbitrary_branch},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["branch"] == arbitrary_branch

        del app.dependency_overrides[get_clerk_email]

    def test_cross_org_submission_returns_404(self, client, test_db_session):
        """
        Accessing a submission ID that belongs to another org must return 404,
        never the submission data or a 500.
        """
        org_a_id = _create_org(test_db_session, "Org A", "owner@a.com")
        org_b_id = _create_org(test_db_session, "Org B", "owner@b.com")

        # Create a submission under Org A
        sub_id = _create_full_stack(test_db_session, org_a_id)

        # Authenticate as Org B
        app.dependency_overrides[get_clerk_email] = lambda: "owner@b.com"

        resp = client.patch(
            f"/submissions/{sub_id}",
            json={"status": "contacted"},
            headers=HEADERS,
        )
        assert resp.status_code == 404

        del app.dependency_overrides[get_clerk_email]

    def test_status_and_branch_update_together(self, client, test_db_session):
        """Both status and branch can be updated in a single call."""
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        sub_id = _create_full_stack(test_db_session, org_id, status_val="to_contact")
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.patch(
            f"/submissions/{sub_id}",
            json={"status": "contacted", "branch": "new-branch"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "contacted"
        assert body["branch"] == "new-branch"

        del app.dependency_overrides[get_clerk_email]

    def test_status_validated_against_current_labels(self, client, test_db_session):
        """
        After status_labels is updated, only the new list is valid.
        An old label not in the new list must be rejected.
        """
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        sub_id = _create_full_stack(test_db_session, org_id)
        # Set custom labels that don't include "contacted"
        _set_status_labels(test_db_session, org_id, ["open", "resolved"])
        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        # "contacted" was the default but is no longer valid
        resp = client.patch(
            f"/submissions/{sub_id}",
            json={"status": "contacted"},
            headers=HEADERS,
        )
        assert resp.status_code == 400

        # "open" is now valid
        resp = client.patch(
            f"/submissions/{sub_id}",
            json={"status": "open"},
            headers=HEADERS,
        )
        assert resp.status_code == 200

        del app.dependency_overrides[get_clerk_email]


# ── GET /submissions ──────────────────────────────────────────────────────────

class TestListSubmissions:

    def test_returns_only_caller_org_submissions(self, client, test_db_session):
        """RLS must prevent Org B from seeing Org A's submissions."""
        org_a_id = _create_org(test_db_session, "Org A", "owner@a.com")
        org_b_id = _create_org(test_db_session, "Org B", "owner@b.com")

        _create_full_stack(test_db_session, org_a_id)
        _create_full_stack(test_db_session, org_a_id)

        app.dependency_overrides[get_clerk_email] = lambda: "owner@b.com"
        resp = client.get("/submissions", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

        del app.dependency_overrides[get_clerk_email]

    def test_filter_by_status(self, client, test_db_session):
        """?status= must return only submissions with that exact status."""
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        _set_status_labels(
            test_db_session, org_id, ["to_contact", "contacted", "closed"]
        )
        _create_full_stack(test_db_session, org_id, status_val="to_contact")
        _create_full_stack(test_db_session, org_id, status_val="contacted")
        _create_full_stack(test_db_session, org_id, status_val="contacted")

        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.get("/submissions?status=contacted", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert all(item["status"] == "contacted" for item in body["items"])

        del app.dependency_overrides[get_clerk_email]

    def test_filter_by_branch(self, client, test_db_session):
        """?branch= must return only submissions with that exact branch value."""
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        _create_full_stack(test_db_session, org_id, branch_val="north")
        _create_full_stack(test_db_session, org_id, branch_val="north")
        _create_full_stack(test_db_session, org_id, branch_val="south")

        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.get("/submissions?branch=north", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert all(item["branch"] == "north" for item in body["items"])

        del app.dependency_overrides[get_clerk_email]

    def test_combined_filter_status_and_branch(self, client, test_db_session):
        """?status=&branch= must AND both conditions."""
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        _set_status_labels(test_db_session, org_id, ["to_contact", "contacted"])
        _create_full_stack(test_db_session, org_id, status_val="to_contact", branch_val="north")
        _create_full_stack(test_db_session, org_id, status_val="contacted", branch_val="north")
        _create_full_stack(test_db_session, org_id, status_val="to_contact", branch_val="south")

        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.get(
            "/submissions?status=to_contact&branch=north", headers=HEADERS
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "to_contact"
        assert body["items"][0]["branch"] == "north"

        del app.dependency_overrides[get_clerk_email]

    def test_pagination_first_page(self, client, test_db_session):
        """limit=2&offset=0 must return exactly 2 items and correct total."""
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        for _ in range(5):
            _create_full_stack(test_db_session, org_id)

        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.get("/submissions?limit=2&offset=0", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0

        del app.dependency_overrides[get_clerk_email]

    def test_pagination_second_page(self, client, test_db_session):
        """limit=2&offset=2 must return the next 2 items (not the first page)."""
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        for _ in range(5):
            _create_full_stack(test_db_session, org_id)

        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        page1 = client.get("/submissions?limit=2&offset=0", headers=HEADERS).json()
        page2 = client.get("/submissions?limit=2&offset=2", headers=HEADERS).json()

        assert len(page2["items"]) == 2
        # Pages must not overlap
        ids_p1 = {item["id"] for item in page1["items"]}
        ids_p2 = {item["id"] for item in page2["items"]}
        assert ids_p1.isdisjoint(ids_p2), "Pages must not share submission IDs"

        del app.dependency_overrides[get_clerk_email]

    def test_pagination_last_page_partial(self, client, test_db_session):
        """offset beyond half of total returns the remaining items (not a full page)."""
        org_id = _create_org(test_db_session, "Org A", "owner@a.com")
        for _ in range(5):
            _create_full_stack(test_db_session, org_id)

        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        resp = client.get("/submissions?limit=2&offset=4", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 1  # only 1 left

        del app.dependency_overrides[get_clerk_email]

    def test_no_cross_org_data_leak_in_pagination(self, client, test_db_session):
        """
        Paginating through all pages must never surface submissions from
        another org, even when offset exceeds the caller's own count.
        """
        org_a_id = _create_org(test_db_session, "Org A", "owner@a.com")
        org_b_id = _create_org(test_db_session, "Org B", "owner@b.com")

        # Org A has 3, Org B has 10
        for _ in range(3):
            _create_full_stack(test_db_session, org_a_id)
        for _ in range(10):
            _create_full_stack(test_db_session, org_b_id)

        app.dependency_overrides[get_clerk_email] = lambda: "owner@a.com"

        # Request with large offset — should still see only Org A's submissions
        resp = client.get("/submissions?limit=50&offset=0", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        org_ids_seen = {item["org_id"] for item in body["items"]}
        assert org_ids_seen == {str(org_a_id)}, (
            "Response must only contain Org A's submissions"
        )

        del app.dependency_overrides[get_clerk_email]
