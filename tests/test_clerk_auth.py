import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from app.api.deps import get_clerk_email

class MockFastAPIRequest:
    def __init__(self):
        self.headers = {"authorization": "Bearer garbage123"}
        self.url = "http://testserver/"

def test_get_clerk_email_garbage_token():
    req = MockFastAPIRequest()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage123")
    
    with pytest.raises(HTTPException) as exc_info:
        # We bypass FastAPI dependency injection and call the function directly
        get_clerk_email(req, creds) # type: ignore
        
    assert exc_info.value.status_code == 401
    assert "Token verification failed" in exc_info.value.detail
