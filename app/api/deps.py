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

from fastapi import Request
from clerk_backend_api.security.types import AuthenticateRequestOptions
from typing import Mapping

class _ClerkRequestWrap:
    def __init__(self, headers: Mapping[str, str], url: str):
        self.headers = headers
        self.url = url

def get_clerk_email(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    Verifies the Clerk JWT token and extracts the user's email.
    """
    clerk = get_clerk_client()
    
    try:
        clerk_req = _ClerkRequestWrap(
            headers=request.headers,
            url=str(request.url)
        )
        req_state = clerk.authenticate_request(clerk_req, AuthenticateRequestOptions())
        
        if not req_state.is_signed_in:
            raise Exception(req_state.message or "Not signed in")
            
        user_id = req_state.payload.get("sub")
        if not user_id:
            raise Exception("No user ID found in token")
            
        user = clerk.users.get(user_id=user_id)
        if not user or not user.email_addresses:
            raise Exception("User has no email address")
            
        return user.email_addresses[0].email_address

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
