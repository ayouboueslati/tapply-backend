import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.api.deps import get_db, get_clerk_email
from tests.conftest import _get_test_url

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
        from sqlalchemy import text
        test_db_session.execute(text("SET ROLE tapply_app"))
        yield test_db_session
        test_db_session.execute(text("RESET ROLE"))
        
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    del app.dependency_overrides[get_db]

def test_unverified_token(client):
    # If no token is provided, 401 Unauthorized is returned by HTTPBearer
    response = client.get("/stands")
    assert response.status_code == 401

def test_invalid_token(client):
    # Provide token but don't override get_clerk_email, so it fails verification
    response = client.get("/stands", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401

def test_verified_token_no_staff_user(client):
    # Override get_clerk_email to simulate a valid token that has no staff user
    app.dependency_overrides[get_clerk_email] = lambda: "notstaff@example.com"
    
    response = client.get("/stands", headers={"Authorization": "Bearer valid"})
    
    # Should be 403 because lookup_staff_org returns no row
    assert response.status_code == 403
    
    # Clean up override
    del app.dependency_overrides[get_clerk_email]

def test_org_creation_uses_token_email(client, test_db_session):
    app.dependency_overrides[get_clerk_email] = lambda: "admin@neworg.com"
    
    response = client.post("/organizations", json={"name": "Test Org"}, headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200
    data = response.json()
    assert "org_id" in data
    
    # Verify the staff_user was created with the email from the token
    # We use test_db_session instead of owner_conn because the data is in an uncommitted transaction
    from sqlalchemy import text
    row = test_db_session.execute(
        text("SELECT email FROM staff_users WHERE org_id = :org_id"), 
        {"org_id": data["org_id"]}
    ).fetchone()
    
    assert row is not None
    assert row[0] == "admin@neworg.com"
    
    # Clean up
    del app.dependency_overrides[get_clerk_email]
