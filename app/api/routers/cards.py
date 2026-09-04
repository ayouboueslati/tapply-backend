"""
app/api/routers/cards.py
─────────────────────────
GET /cards  — Lists all cards belonging to the caller's organization.

Cards have no org_id column; RLS enforces access via a join-based subquery on
stands (stand_id IN (SELECT id FROM stands WHERE org_id = current_setting(...))).
This endpoint surfaces the card token so org staff can share the public tap URL
(/tap/{token}) with candidates.

Auth: same get_current_staff_user dependency as every other admin endpoint.
No client-supplied org_id — RLS + staff context handle scoping.
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_staff_user, StaffUserContext
from app.models.card import Card
from app.models.stand import Stand
from app.schemas import CardResponse, CardUpdate

router = APIRouter(prefix="/cards", tags=["cards"])


@router.get("", response_model=List[CardResponse])
def list_cards(
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    """
    Returns all cards for the caller's organization, with the stand name
    denormalized for display convenience.

    RLS scoping: cards are filtered by joining to stands, which are already
    scoped to org_id = current_setting('app.current_org_id') by RLS.
    This query does not require an explicit org_id filter in the WHERE clause —
    the DB-level policy handles it.
    """
    rows = session.execute(
        select(Card, Stand.name.label("stand_name"))
        .join(Stand, Card.stand_id == Stand.id)
        .order_by(Stand.name, Card.id)
    ).all()

    return [
        CardResponse(
            id=card.id,
            stand_id=card.stand_id,
            stand_name=stand_name,
            token=card.token,
            is_active=card.is_active,
            assigned_recruiter_id=card.assigned_recruiter_id
        )
        for card, stand_name in rows
    ]

@router.patch("/{card_id}", response_model=CardResponse)
def update_card(
    card_id: str,
    payload: CardUpdate,
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    from fastapi import HTTPException, status
    if not staff.can_edit:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to edit cards.")

    # Using the same subquery logic implicitly through RLS by just selecting the Card
    row = session.execute(
        select(Card, Stand.name.label("stand_name"))
        .join(Stand, Card.stand_id == Stand.id)
        .where(Card.id == card_id)
    ).first()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found.")

    card, stand_name = row

    if payload.is_active is not None:
        card.is_active = payload.is_active
    if payload.assigned_recruiter_id is not None:
        card.assigned_recruiter_id = payload.assigned_recruiter_id

    session.commit()
    session.refresh(card)

    return CardResponse(
        id=card.id,
        stand_id=card.stand_id,
        stand_name=stand_name,
        token=card.token,
        is_active=card.is_active,
        assigned_recruiter_id=card.assigned_recruiter_id
    )
