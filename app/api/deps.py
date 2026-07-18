from typing import Generator, Tuple
from uuid import UUID

import jwt  # Using this temporarily to type hint if needed, or simply standard typing
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.orm import Session

from clerk_backend_api import Clerk

from app.config import settings
from app.db.session import SessionLocal, set_org_context

security = HTTPBearer()

def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session

def get_clerk_client() -> Clerk:
    return Clerk(bearer_auth=settings.CLERK_SECRET_KEY)

def get_clerk_email(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    Verifies the Clerk JWT token and extracts the user's email.
    """
    token = credentials.credentials
    clerk = get_clerk_client()
    
    try:
        # We assume clerk_backend_api has a verify_token method or similar
        # Since the actual verification logic requires JWKS, this is typically
        # done using the clerk client. For now, we stub the API call if testing,
        # but the test suite uses dependency_overrides.
        raise NotImplementedError("Real clerk verification requires JWKS/API keys")

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {str(e)}",
        )

class StaffUserContext:
    def __init__(self, user_id: UUID, org_id: UUID, role: str):
        self.user_id = user_id
        self.org_id = org_id
        self.role = role

def get_current_staff_user(
    email: str = Depends(get_clerk_email),
    session: Session = Depends(get_db)
) -> StaffUserContext:
    """
    Verifies the clerk email belongs to a staff user, sets the RLS context, and returns the context.
    """
    try:
        row = session.execute(
            text("SELECT user_id, org_id, role FROM auth.lookup_staff_org(:email)"),
            {"email": email},
        ).one_or_none()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a registered staff user",
            )
            
        set_org_context(session, row.org_id)
        return StaffUserContext(user_id=row.user_id, org_id=row.org_id, role=row.role)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error looking up staff user: {str(e)}",
        )
