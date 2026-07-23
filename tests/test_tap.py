import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.main import app, limiter
from app.api.deps import get_db, get_clerk_email
from tests.conftest import _get_test_url
import json

engine = create_engine(_get_test_url())
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def test_db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    
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

@pytest.fixture(autouse=True)
def reset_limiter():
    """Reset the rate limiter state before each test to prevent test pollution."""
    limiter._storage.reset()
    yield

def create_org_stand_card(session, org_name, email, default_branch, form_fields):
    # Bypass RLS to create data directly for setup
    row = session.execute(
        text(
            "SELECT org_id, admin_user_id "
            "FROM auth.create_organization(:name, :status, :email, :role)"
        ),
        {
            "name": org_name,
            "status": "active",
            "email": email,
            "role": "owner",
        },
    ).one()
    org_id = row.org_id
    session.commit()

    # Create form_schema
    session.execute(
        text("INSERT INTO form_schemas (org_id, fields) VALUES (:org_id, :fields)"),
        {"org_id": org_id, "fields": json.dumps(form_fields)}
    )

    # Create stand
    row = session.execute(
        text("INSERT INTO stands (org_id, name, default_branch) VALUES (:org_id, 'Test Stand', :default_branch) RETURNING id"),
        {"org_id": org_id, "default_branch": default_branch}
    ).one()
    stand_id = row.id

    # Create card
    token = str(uuid.uuid4())
    session.execute(
        text("INSERT INTO cards (stand_id, token) VALUES (:stand_id, :token)"),
        {"stand_id": stand_id, "token": token}
    )
    
    session.commit()
    return org_id, stand_id, token

def test_get_tap_valid_token(client, test_db_session):
    form_fields = [{"name": "email", "required": True}]
    _, _, token = create_org_stand_card(test_db_session, "Org A", "user@test.com", "Branch A", form_fields)
    
    response = client.get(f"/tap/{token}")
    assert response.status_code == 200
    data = response.json()
    assert data["org_name"] == "Org A"
    assert data["default_branch"] == "Branch A"
    assert data["form_fields"] == form_fields

def test_get_tap_invalid_token(client):
    response = client.get(f"/tap/invalid-token")
    assert response.status_code == 404

def test_post_tap_submit_success_with_branch_precedence(client, test_db_session):
    form_fields = [{"name": "email", "required": True}, {"name": "name", "required": False}]
    org_id, stand_id, token = create_org_stand_card(test_db_session, "Org A", "user@test.com", "Branch A", form_fields)
    
    # 1. Submit using default_branch
    payload_1 = {
        "idempotency_key": str(uuid.uuid4()),
        "consent": True,
        "data": {"email": "test1@example.com"}
    }
    response = client.post(f"/tap/{token}/submit", json=payload_1)
    assert response.status_code == 201
    
    # 2. Submit with explicit branch override
    payload_2 = {
        "idempotency_key": str(uuid.uuid4()),
        "consent": True,
        "data": {"email": "test2@example.com", "branch": "Override Branch"}
    }
    response = client.post(f"/tap/{token}/submit", json=payload_2)
    assert response.status_code == 201

    # Verify branch logic via direct DB query (bypassing RLS as superuser)
    submissions = test_db_session.execute(text("SELECT branch, data FROM submissions ORDER BY created_at ASC")).fetchall()
    assert len(submissions) == 2
    assert submissions[0].branch == "Branch A"
    assert submissions[0].data["email"] == "test1@example.com"
    
    assert submissions[1].branch == "Override Branch"
    assert submissions[1].data["email"] == "test2@example.com"

def test_post_tap_submit_missing_consent(client, test_db_session):
    form_fields = [{"name": "email", "required": True}]
    _, _, token = create_org_stand_card(test_db_session, "Org A", "user@test.com", "Branch A", form_fields)
    
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "consent": False,
        "data": {"email": "test@example.com"}
    }
    response = client.post(f"/tap/{token}/submit", json=payload)
    assert response.status_code == 400
    assert "Consent is required" in response.text
    
    # Missing consent completely will fail Pydantic schema validation (422)
    payload_missing = {"idempotency_key": str(uuid.uuid4()), "data": {"email": "test@example.com"}}
    response = client.post(f"/tap/{token}/submit", json=payload_missing)
    assert response.status_code == 422

def test_post_tap_submit_missing_required_fields(client, test_db_session):
    form_fields = [{"name": "email", "required": True}, {"name": "phone", "required": True}]
    _, _, token = create_org_stand_card(test_db_session, "Org A", "user@test.com", "Branch A", form_fields)
    
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "consent": True,
        "data": {"email": "test@example.com"} # missing phone
    }
    response = client.post(f"/tap/{token}/submit", json=payload)
    assert response.status_code == 400
    assert "Missing required field: phone" in response.text

def test_post_tap_submit_client_org_id_ignored(client, test_db_session):
    # Prove that submitting a fake org_id in the payload does not inject that org_id
    # into the database. We check this by querying as the real org's context.
    form_fields = [{"name": "email", "required": True}]
    real_org_id, _, token = create_org_stand_card(test_db_session, "Org A", "user@test.com", None, form_fields)
    
    fake_org_id = str(uuid.uuid4())
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "consent": True,
        "data": {"email": "test@example.com", "org_id": fake_org_id}
    }
    response = client.post(f"/tap/{token}/submit", json=payload)
    assert response.status_code == 201
    
    row = test_db_session.execute(text("SELECT org_id FROM submissions")).one()
    assert row.org_id == real_org_id
    assert row.org_id != fake_org_id

def test_cross_org_isolation(client, test_db_session):
    # Submissions made under Org A are invisible when queried under Org B's context
    form_fields = [{"name": "email", "required": True}]
    org_a_id, _, token_a = create_org_stand_card(test_db_session, "Org A", "user_a@test.com", None, form_fields)
    org_b_id, _, token_b = create_org_stand_card(test_db_session, "Org B", "user_b@test.com", None, form_fields)
    
    client.post(f"/tap/{token_a}/submit", json={"idempotency_key": str(uuid.uuid4()), "consent": True, "data": {"email": "a@example.com"}})
    
    # Query as org B using set_org_context
    test_db_session.execute(text("SET ROLE tapply_app"))
    test_db_session.execute(text(f"SET app.current_org_id = '{org_b_id}'"))
    
    rows = test_db_session.execute(text("SELECT * FROM submissions")).fetchall()
    assert len(rows) == 0

def test_rate_limit(client, test_db_session):
    form_fields = [{"name": "email", "required": True}]
    _, _, token = create_org_stand_card(test_db_session, "Org A", "user@test.com", None, form_fields)
    
    # Limit is 30/minute, so 31st request should fail
    for i in range(30):
        response = client.get(f"/tap/{token}")
        assert response.status_code == 200
        
    response = client.get(f"/tap/{token}")
    assert response.status_code == 429
    assert "Rate limit exceeded" in response.text

def test_payload_size_limit(client, test_db_session):
    form_fields = [{"name": "email", "required": True}]
    _, _, token = create_org_stand_card(test_db_session, "Org A", "user@test.com", None, form_fields)
    
    # Construct a huge payload > 50KB
    huge_string = "a" * (60 * 1024)
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "consent": True,
        "data": {"email": "test@example.com", "huge": huge_string}
    }
    
    response = client.post(f"/tap/{token}/submit", json=payload)
    assert response.status_code == 413

def test_post_tap_submit_idempotent_retry(client, test_db_session):
    form_fields = [{"name": "email", "required": True}]
    _, _, token = create_org_stand_card(test_db_session, "Org A", "user@test.com", "Branch A", form_fields)
    
    idem_key = str(uuid.uuid4())
    payload = {
        "idempotency_key": idem_key,
        "consent": True,
        "data": {"email": "test@example.com"}
    }
    
    # First submit
    res1 = client.post(f"/tap/{token}/submit", json=payload)
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["status"] == "ok"
    sub_id = data1["submission_id"]
    
    # Second submit (retry)
    res2 = client.post(f"/tap/{token}/submit", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "ok"
    assert data2["submission_id"] == sub_id
    
    # DB should have only 1 row
    submissions = test_db_session.execute(text("SELECT * FROM submissions")).fetchall()
    assert len(submissions) == 1

def test_post_tap_submit_cross_org_idempotency_key_collision(client, test_db_session):
    form_fields = [{"name": "email", "required": True}]
    org_a_id, _, token_a = create_org_stand_card(test_db_session, "Org A", "user_a@test.com", "Branch A", form_fields)
    org_b_id, _, token_b = create_org_stand_card(test_db_session, "Org B", "user_b@test.com", "Branch B", form_fields)
    
    idem_key = str(uuid.uuid4())
    
    payload_a = {
        "idempotency_key": idem_key,
        "consent": True,
        "data": {"email": "a@example.com"}
    }
    res_a = client.post(f"/tap/{token_a}/submit", json=payload_a)
    assert res_a.status_code == 201
    
    payload_b = {
        "idempotency_key": idem_key,
        "consent": True,
        "data": {"email": "b@example.com"}
    }
    res_b = client.post(f"/tap/{token_b}/submit", json=payload_b)
    assert res_b.status_code == 201
    
    # Both inserts should succeed despite the exact same idempotency_key (since org_id differs)
    submissions = test_db_session.execute(text("SELECT id FROM submissions")).fetchall()
    assert len(submissions) == 2
