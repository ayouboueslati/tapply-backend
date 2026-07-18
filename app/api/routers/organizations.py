from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_clerk_email
from app.schemas import OrganizationCreate

router = APIRouter(prefix="/organizations", tags=["organizations"])

@router.post("", response_model=dict)
def create_organization(
    org_in: OrganizationCreate,
    email: str = Depends(get_clerk_email),
    session: Session = Depends(get_db),
):
    """
    Creates a new organization and provisions the initial owner staff_user
    using the email verified from the Clerk token.
    """
    row = session.execute(
        text(
            "SELECT org_id, admin_user_id "
            "FROM auth.create_organization(:name, :status, :email, :role)"
        ),
        {
            "name": org_in.name,
            "status": "active",
            "email": email,
            "role": "owner",
        },
    ).one()
    
    session.commit()
    
    return {"org_id": row.org_id}
