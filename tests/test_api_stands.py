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
    # Using create_savepoint allows the app to call session.commit() 
    # without actually committing the outer transaction.
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


def create_org_and_staff(session, org_name, email):
    # Bypass RLS to create org and user directly or via auth.create_organization
    from sqlalchemy import text
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
    session.commit()
    return row.org_id

def test_stand_crud_happy_path(client, test_db_session):
    # 1. Setup Org A
    org_id = create_org_and_staff(test_db_session, "Org A", "user_a@example.com")
    
    app.dependency_overrides[get_clerk_email] = lambda: "user_a@example.com"
    
    headers = {"Authorization": "Bearer dummy"}
    
    # 2. Create Stand
    response = client.post("/stands", json={"name": "Front Desk"}, headers=headers)
    assert response.status_code == 200
    stand = response.json()
    assert stand["name"] == "Front Desk"
    assert stand["org_id"] == str(org_id)
    stand_id = stand["id"]
    
    # 3. Read Stands
    response = client.get("/stands", headers=headers)
    assert response.status_code == 200
    stands = response.json()
    assert len(stands) == 1
    assert stands[0]["id"] == stand_id
    
    # 4. Update Stand
    response = client.patch(f"/stands/{stand_id}", json={"name": "Back Desk"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Back Desk"
    
    # 5. Delete Stand
    response = client.delete(f"/stands/{stand_id}", headers=headers)
    assert response.status_code == 204
    
    # Verify deletion
    response = client.get("/stands", headers=headers)
    assert len(response.json()) == 0
    
    del app.dependency_overrides[get_clerk_email]


def test_cross_org_stand_access_returns_404(client, test_db_session):
    # 1. Setup Org A and Org B
    org_a_id = create_org_and_staff(test_db_session, "Org A", "user_a@example.com")
    org_b_id = create_org_and_staff(test_db_session, "Org B", "user_b@example.com")
    
    # Create a stand in Org A
    app.dependency_overrides[get_clerk_email] = lambda: "user_a@example.com"
    response = client.post("/stands", json={"name": "Org A Stand"}, headers={"Authorization": "Bearer dummy"})
    assert response.status_code == 200
    stand_id = response.json()["id"]
    
    # Switch to Org B
    app.dependency_overrides[get_clerk_email] = lambda: "user_b@example.com"
    
    # Read should return empty list (RLS hides Org A's stands)
    response = client.get("/stands", headers={"Authorization": "Bearer dummy"})
    assert response.status_code == 200
    assert len(response.json()) == 0
    
    # Update should return 404
    response = client.patch(f"/stands/{stand_id}", json={"name": "Hacked"}, headers={"Authorization": "Bearer dummy"})
    assert response.status_code == 404
    
    # Delete should return 404
    response = client.delete(f"/stands/{stand_id}", headers={"Authorization": "Bearer dummy"})
    assert response.status_code == 404
    
    del app.dependency_overrides[get_clerk_email]
