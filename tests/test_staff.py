import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta, timezone
import uuid

from app.main import app
from app.api.deps import get_db, get_clerk_email
from app.models.staff_user import StaffUser
from app.models.organization import Organization
from tests.conftest import _get_test_url

engine = create_engine(_get_test_url())
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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

def _client_factory(test_db_session, client_fixture, email: str):
    def override_get_clerk_email():
        return email
    app.dependency_overrides[get_clerk_email] = override_get_clerk_email
    return client_fixture

@pytest.fixture(scope="function")
def owner_email():
    return "owner@example.com"

@pytest.fixture(scope="function")
def org_context(test_db_session, owner_email):
    test_db_session.execute(text("SET ROLE postgres"))
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    test_db_session.execute(
        text("INSERT INTO organizations (id, name, billing_status) VALUES (:id, :name, 'active')"),
        {"id": org_id, "name": "Primary Org"}
    )
    test_db_session.execute(
        text("INSERT INTO staff_users (id, org_id, email, role) VALUES (:id, :org_id, :email, 'org_owner')"),
        {"id": user_id, "org_id": org_id, "email": owner_email}
    )
    test_db_session.commit()
    test_db_session.execute(text("RESET ROLE"))
    return {"org_id": org_id, "owner_id": user_id}

@pytest.fixture(scope="function")
def owner_client(test_db_session, client, owner_email, org_context):
    return _client_factory(test_db_session, client, owner_email)

@pytest.fixture
def other_org_staff(test_db_session):
    test_db_session.execute(text("SET ROLE postgres"))
    org = Organization(name="Other Org")
    test_db_session.add(org)
    test_db_session.flush()
    staff = StaffUser(
        org_id=org.id,
        email="other@example.com",
        role="staff"
    )
    test_db_session.add(staff)
    test_db_session.commit()
    test_db_session.execute(text("RESET ROLE"))
    return staff

@pytest.fixture
def regular_staff(test_db_session, org_context):
    test_db_session.execute(text("SET ROLE postgres"))
    staff = StaffUser(
        org_id=org_context["org_id"],
        email="regular_staff@test.com",
        role="staff"
    )
    test_db_session.add(staff)
    test_db_session.commit()
    test_db_session.execute(text("RESET ROLE"))
    return staff


def test_get_staff_members(owner_client, regular_staff, other_org_staff, owner_email):
    response = owner_client.get("/staff")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 2
    emails = {item["email"] for item in data}
    assert owner_email in emails
    assert "regular_staff@test.com" in emails
    assert "other@example.com" not in emails


def test_owner_can_grant_and_revoke_permissions(owner_client, test_db_session, regular_staff):
    res = owner_client.patch(
        f"/staff/{regular_staff.id}/permissions",
        json={"can_edit": True, "can_edit_until": None}
    )
    assert res.status_code == 204

    test_db_session.execute(text("SET ROLE postgres"))
    test_db_session.refresh(regular_staff)
    test_db_session.execute(text("RESET ROLE"))
    assert regular_staff.can_edit is True
    assert regular_staff.can_edit_until is None

    res = owner_client.patch(
        f"/staff/{regular_staff.id}/permissions",
        json={"can_edit": False, "can_edit_until": None}
    )
    assert res.status_code == 204

    test_db_session.execute(text("SET ROLE postgres"))
    test_db_session.refresh(regular_staff)
    test_db_session.execute(text("RESET ROLE"))
    assert regular_staff.can_edit is False


def test_owner_can_grant_time_limited_permissions(owner_client, test_db_session, regular_staff):
    future_date = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    
    res = owner_client.patch(
        f"/staff/{regular_staff.id}/permissions",
        json={"can_edit": True, "can_edit_until": future_date}
    )
    assert res.status_code == 204

    test_db_session.execute(text("SET ROLE postgres"))
    test_db_session.refresh(regular_staff)
    test_db_session.execute(text("RESET ROLE"))
    assert regular_staff.can_edit is True
    assert regular_staff.can_edit_until is not None


def test_cannot_set_can_edit_until_if_can_edit_false(owner_client, regular_staff):
    future_date = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    
    res = owner_client.patch(
        f"/staff/{regular_staff.id}/permissions",
        json={"can_edit": False, "can_edit_until": future_date}
    )
    assert res.status_code == 400


def test_non_owner_cannot_modify_permissions(test_db_session, client, regular_staff):
    staff_client = _client_factory(test_db_session, client, regular_staff.email)
    
    res = staff_client.patch(
        f"/staff/{regular_staff.id}/permissions",
        json={"can_edit": True}
    )
    assert res.status_code == 403
    assert "owner" in res.json()["detail"]


def test_owner_cannot_modify_own_permissions(owner_client, org_context):
    res = owner_client.patch(
        f"/staff/{org_context['owner_id']}/permissions",
        json={"can_edit": False}
    )
    assert res.status_code == 400
    assert "own permissions" in res.json()["detail"]


def test_cannot_modify_staff_in_another_org(owner_client, other_org_staff):
    res = owner_client.patch(
        f"/staff/{other_org_staff.id}/permissions",
        json={"can_edit": True}
    )
    assert res.status_code == 404

