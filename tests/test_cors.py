from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_cors_allowed_origin():
    """
    Test that the CORS middleware allows requests from the configured FRONTEND_URLS
    and returns the appropriate Access-Control-Allow-Origin header.
    """
    origin = "http://localhost:3000"
    
    # Send an OPTIONS preflight request
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    
    assert response.status_code == 200
    # The header should be present and match the requested origin (since it's allowed)
    assert "access-control-allow-origin" in response.headers
    assert response.headers["access-control-allow-origin"] == origin

def test_cors_disallowed_origin():
    """
    Test that a disallowed origin does not receive the Access-Control-Allow-Origin header.
    """
    origin = "http://evil.com"
    
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    
    assert response.status_code == 400
    # For disallowed origins, FastAPI's CORSMiddleware rejects the preflight request
    assert "access-control-allow-origin" not in response.headers
