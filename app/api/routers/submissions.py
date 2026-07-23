"""
app/api/routers/submissions.py
──────────────────────────────
Submission management endpoints for authenticated staff.

Routes
------
GET  /submissions
    List submissions for the caller's org with optional filters and pagination.
    Any authenticated staff role may call this.

    Query parameters:
      status (str, optional): Filter by exact status label.
      branch (str, optional): Filter by exact branch string.
      limit  (int, default 50): Max rows per page.
      offset (int, default 0):  Row offset for pagination.

    Returns: { items: [...], total: int, limit: int, offset: int }

    RLS scoping: get_current_staff_user sets app.current_org_id via
    set_org_context, so the query naturally sees only the caller's org.
    Cross-org data never appears — RLS enforces this at the DB layer.

PATCH /submissions/{id}
    Update the status and/or branch of a single submission.
    Any authenticated staff role may call this.

    Status validation:
      ``status`` is validated against the org's current ``status_labels``
      list at the application layer (not a DB constraint).  This is an
      explicit trade-off: flexibility over referential integrity.  Direct
      DB writes can bypass this check, but application clients cannot.
      Invalid status → 400.

    Branch validation:
      ``branch`` accepts any string without further validation — consistent
      with how candidates submit it in Step 3's public tap endpoint.

    Cross-org access:
      session.get(Submission, id) under RLS returns None for any submission
      not belonging to the caller's org → 404.  A 500 or data leak is not
      possible because the SELECT itself is filtered by RLS.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_staff_user, get_db, StaffUserContext
from app.models.organization import Organization
from app.models.submission import Submission
from app.schemas import SubmissionListResponse, SubmissionResponse, SubmissionUpdate

router = APIRouter(prefix="/submissions", tags=["submissions"])

# Default page size — chosen to be practical for dashboard use while
# preventing accidental full-table scans on large orgs.
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


@router.get("", response_model=SubmissionListResponse)
def list_submissions(
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
    status_filter: Optional[str] = Query(None, alias="status"),
    branch: Optional[str] = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """
    Returns a paginated list of submissions for the caller's org.

    RLS (set by get_current_staff_user) ensures cross-org data is never
    returned — no explicit org_id filter is required in the query, but it
    is included defensively for query-plan clarity.

    Filters:
      - ``?status=<label>`` — exact match on the status column.
      - ``?branch=<text>``  — exact match on the branch column.

    Pagination:
      - ``?limit=N``  — max rows returned (1–200, default 50).
      - ``?offset=N`` — row offset (default 0).
    """
    base_query = (
        select(Submission)
        .where(Submission.org_id == staff.org_id)
    )

    if status_filter is not None:
        base_query = base_query.where(Submission.status == status_filter)
    if branch is not None:
        base_query = base_query.where(Submission.branch == branch)

    # Total count (same filters, no pagination)
    count_query = select(func.count()).select_from(base_query.subquery())
    total: int = session.scalar(count_query) or 0

    # Paginated rows — stable ordering by creation time
    rows = session.scalars(
        base_query.order_by(Submission.created_at.desc()).limit(limit).offset(offset)
    ).all()

    return SubmissionListResponse(
        items=rows,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/{submission_id}", response_model=SubmissionResponse)
def update_submission(
    submission_id: uuid.UUID,
    body: SubmissionUpdate,
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    """
    Update the status and/or branch of a submission.

    **Status validation (application-level, not DB enum)**
    The endpoint loads the org's ``status_labels`` list and rejects any
    ``status`` value not present in that list with a 400 error naming the
    valid options.  This validation happens at write time — it reflects the
    org's *current* label list, not the label that was valid when the
    submission was created.

    **Cross-org access → 404**
    ``session.get(Submission, submission_id)`` runs under RLS.  If the
    submission belongs to a different org the DB returns no row and the
    endpoint raises 404.  The calling client cannot distinguish between
    "does not exist" and "belongs to another org" — this is intentional.
    """
    # RLS guarantees this returns None for cross-org IDs.
    submission = session.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if body.status is not None:
        # Load the org's current valid label list.
        # session.get(Organization, ...) is RLS-scoped — org_id from the
        # staff context is the same org the submission belongs to.
        org = session.get(Organization, staff.org_id)
        if org is None:
            # Defensive — should never happen for a valid staff session.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        valid_labels = org.status_labels
        if body.status not in valid_labels:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid status {body.status!r}. "
                    f"Valid labels for this org: {valid_labels}"
                ),
            )
        submission.status = body.status

    if body.branch is not None:
        # Free text — no validation (consistent with Step 3 tap submission).
        submission.branch = body.branch

    session.commit()

    return submission
