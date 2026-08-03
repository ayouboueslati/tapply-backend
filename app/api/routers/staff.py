from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List
from uuid import UUID

from app.api.deps import get_db, get_current_staff_user, StaffUserContext
from app.schemas import StaffMemberResponse, StaffPermissionUpdate

router = APIRouter(prefix="/staff", tags=["staff"])

@router.get("", response_model=List[StaffMemberResponse])
def get_staff_members(
    session: Session = Depends(get_db),
    staff: StaffUserContext = Depends(get_current_staff_user),
):
    """
    Returns a list of all staff members belonging to the caller's organization.
    """
    # Use the SECURITY DEFINER function to bypass the table-level restrictions.
    # We pass the org_id from the verified JWT context to ensure isolation.
    rows = session.execute(
        text("SELECT id, email, role, can_edit, can_edit_until, created_at FROM auth.list_org_staff(:org_id)"),
        {"org_id": staff.org_id},
    ).mappings().all()

    return rows

@router.patch("/{user_id}/permissions", status_code=status.HTTP_204_NO_CONTENT)
def update_staff_permissions(
    user_id: UUID,
    payload: StaffPermissionUpdate,
    session: Session = Depends(get_db),
    staff: StaffUserContext = Depends(get_current_staff_user),
):
    """
    Updates the 'can_edit' permission for a staff member.
    Only the org_owner can perform this action.
    """
    if staff.role != "org_owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organization owner can manage team permissions.",
        )

    if user_id == staff.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot modify your own permissions.",
        )

    if payload.can_edit_until is not None and not payload.can_edit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="can_edit_until can only be set when can_edit is true.",
        )

    # Verify the target user exists and is in the same organization
    target_row = session.execute(
        text("SELECT role FROM auth.list_org_staff(:org_id) WHERE id = :user_id"),
        {"org_id": staff.org_id, "user_id": user_id},
    ).mappings().one_or_none()

    if not target_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Staff member not found in your organization.",
        )

    if target_row["role"] == "org_owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify permissions of an organization owner.",
        )

    # Perform the update via the SECURITY DEFINER function
    session.execute(
        text("SELECT auth.update_staff_permissions(:org_id, :user_id, :can_edit, :can_edit_until)"),
        {
            "org_id": staff.org_id,
            "user_id": user_id,
            "can_edit": payload.can_edit,
            "can_edit_until": payload.can_edit_until,
        },
    )
    session.commit()
