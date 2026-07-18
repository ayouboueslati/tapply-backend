import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_staff_user, StaffUserContext
from app.models.stand import Stand
from app.schemas import StandCreate, StandUpdate, StandResponse

router = APIRouter(prefix="/stands", tags=["stands"])

@router.post("", response_model=StandResponse)
def create_stand(
    stand_in: StandCreate,
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    """Creates a stand for the caller's organization."""
    stand = Stand(
        org_id=staff.org_id,
        name=stand_in.name,
        default_branch=stand_in.default_branch,
    )
    session.add(stand)
    session.commit()
    session.refresh(stand)
    return stand

@router.get("", response_model=List[StandResponse])
def list_stands(
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    """Lists stands for the caller's organization (scoped via RLS)."""
    stands = session.scalars(select(Stand)).all()
    return stands

@router.patch("/{stand_id}", response_model=StandResponse)
def update_stand(
    stand_id: uuid.UUID,
    stand_in: StandUpdate,
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    """Updates a stand. Returns 404 if not found (or in another org)."""
    stand = session.get(Stand, stand_id)
    if not stand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stand not found")
        
    if stand_in.name is not None:
        stand.name = stand_in.name
    if stand_in.default_branch is not None:
        stand.default_branch = stand_in.default_branch
        
    session.commit()
    session.refresh(stand)
    return stand

@router.delete("/{stand_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stand(
    stand_id: uuid.UUID,
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    """Deletes a stand. Returns 404 if not found (or in another org)."""
    stand = session.get(Stand, stand_id)
    if not stand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stand not found")
        
    session.delete(stand)
    session.commit()
