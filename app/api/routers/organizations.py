"""
app/api/routers/organizations.py
────────────────────────────────
Organization management endpoints.

Routes
------
POST /organizations
    Create a new organization + initial owner staff_user.
    Uses auth.create_organization (SECURITY DEFINER) because FORCE RLS
    blocks direct INSERTs without a pre-existing org context.

GET  /organizations/me/status-labels
    Returns the caller's org's current ordered status label list.
    Any authenticated staff role may call this (read-only).

PATCH /organizations/me/status-labels
    Replaces the caller's org's status label list.
    Restricted to org_owner role — 403 for regular staff.

    Atomicity guarantee: ALL validation (input checks + in-use DB check)
    runs before any write.  If a single removed label is in use the entire
    request is rejected and the labels remain unchanged.

    Input validation (400 on failure):
      - List must be non-empty.
      - No duplicate entries (case-sensitive).
      - Each label ≤ 50 characters.

    Orphan protection (409 on failure):
      - Computes removed = set(current) - set(incoming).
      - Queries submissions WHERE status IN (removed labels) AND org_id = <org>.
      - Rejects if any existing submission still uses a removed label.
      - Renaming: caller must first migrate all affected submissions to the
        new label name, then call this endpoint.  There is no atomic rename
        primitive — this limitation is by design (application-level label
        management, not a DB enum).
"""

from typing import Set

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_clerk_email, get_current_staff_user, StaffUserContext
from app.models.form_schema import FormSchema
from app.models.organization import Organization
from app.models.submission import Submission
from app.schemas import OrganizationCreate, StatusLabelsResponse, StatusLabelsUpdate, StaffContextResponse, BranchLabelsResponse, BranchLabelsUpdate

# Maximum allowed length for a single status label (dashboard-facing text).
_MAX_LABEL_LENGTH = 50

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
            "role": "org_owner",
        },
    ).one()

    session.commit()

    return {"org_id": row.org_id}


# ── Staff Context endpoint ────────────────────────────────────────────────────

@router.get("/me/context", response_model=StaffContextResponse)
def get_staff_context(
    staff: StaffUserContext = Depends(get_current_staff_user),
    email: str = Depends(get_clerk_email),
    session: Session = Depends(get_db),
):
    """
    Returns the authenticated staff user's email and organization name.
    Useful for the frontend dashboard placeholder.
    """
    org = session.get(Organization, staff.org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
        
    form_fields = session.scalar(
        select(FormSchema.fields).where(FormSchema.org_id == staff.org_id)
    )
    
    return StaffContextResponse(
        email=email, 
        org_name=org.name,
        role=staff.role,
        form_fields=form_fields if form_fields is not None else []
    )


# ── Status label endpoints ────────────────────────────────────────────────────


@router.get("/me/status-labels", response_model=StatusLabelsResponse)
def get_status_labels(
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    """
    Returns the caller's org's current ordered status label list.

    Any authenticated staff role (org_owner or regular staff) may call this.
    RLS ensures only the caller's own org row is visible — no org_id scoping
    is needed in the query beyond what RLS already enforces.
    """
    org = session.get(Organization, staff.org_id)
    if not org:
        # Should never happen for a valid staff session, but be defensive.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return StatusLabelsResponse(status_labels=org.status_labels)


@router.patch("/me/status-labels", response_model=StatusLabelsResponse)
def update_status_labels(
    body: StatusLabelsUpdate,
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    """
    Replaces the caller's org's status label list (org_owner role only).

    The operation is fully atomic: all validation and in-use checks run before
    any database write.  If *any* condition fails, the labels are left unchanged.

    **Input validation (400)**
    - The list must be non-empty.
    - No duplicate entries (case-sensitive).
    - Each label must be ≤ 50 characters.

    **Orphan protection (409)**
    The endpoint computes which labels would be *removed* (``set(current) -
    set(incoming)``) and queries the database to confirm none of them are
    currently referenced by any submission.

    Renaming limitation: there is no atomic rename primitive.  To rename label
    X → Y, the caller must:
      1. Update all submissions that use status X to status Y
         (via PATCH /submissions/{id}).
      2. Then call this endpoint with X removed and Y added.
    Skipping step 1 will result in a 409 listing the blocking label(s).
    """
    # ── Role check ────────────────────────────────────────────────────────────
    if staff.role != "org_owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only org_owner role may manage status labels",
        )

    new_labels = body.status_labels

    # ── Input validation (runs before any DB query) ───────────────────────────

    # 1. Non-empty
    if not new_labels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status_labels must not be empty",
        )

    # 2. No duplicates (case-sensitive)
    seen: Set[str] = set()
    for label in new_labels:
        if label in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate label: {label!r}",
            )
        seen.add(label)

    # 3. Length cap
    too_long = [lbl for lbl in new_labels if len(lbl) > _MAX_LABEL_LENGTH]
    if too_long:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Labels must be ≤ {_MAX_LABEL_LENGTH} characters. "
                f"Offending: {too_long}"
            ),
        )

    # ── Fetch current labels ──────────────────────────────────────────────────
    org = session.get(Organization, staff.org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    current_labels: Set[str] = set(org.status_labels)
    incoming_labels: Set[str] = set(new_labels)
    removed_labels: Set[str] = current_labels - incoming_labels

    # ── In-use check (real DB query, not trust-the-caller) ───────────────────
    # Query for ALL removed labels in a single round-trip.  If *any* of them
    # are referenced by an existing submission the whole request is rejected.
    if removed_labels:
        in_use = session.scalars(
            select(Submission.status)
            .where(Submission.org_id == staff.org_id)
            .where(Submission.status.in_(removed_labels))
            .distinct()
        ).all()

        if in_use:
            labels_str = ", ".join(f'"{label}"' for label in sorted(in_use))
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot remove {labels_str}. This label is still "
                    "referenced by existing submissions. Please move those submissions "
                    "to a different status first, then try again."
                ),
            )

    # ── Write — only reached if all checks pass ───────────────────────────────
    org.status_labels = new_labels
    session.commit()

    return StatusLabelsResponse(status_labels=new_labels)


# ── Step 11: Branch labels (Mirrors Status Labels) ──────────────────────────

@router.get("/me/branches", response_model=BranchLabelsResponse)
def get_branch_labels(
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    """
    Returns the caller's org's current ordered branch label list.

    Any authenticated staff role (org_owner or regular staff) may call this.
    RLS ensures only the caller's own org row is visible.
    """
    org = session.get(Organization, staff.org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return BranchLabelsResponse(branch_labels=org.branch_labels)


@router.patch("/me/branches", response_model=BranchLabelsResponse)
def update_branch_labels(
    body: BranchLabelsUpdate,
    staff: StaffUserContext = Depends(get_current_staff_user),
    session: Session = Depends(get_db),
):
    """
    Replaces the caller's org's branch label list (org_owner role only).
    Mirrors the atomicity and validation rules of status labels exactly.
    """
    # ── Role check ────────────────────────────────────────────────────────────
    if staff.role != "org_owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only org_owner role may manage branch labels",
        )

    new_labels = body.branch_labels

    # ── Input validation (runs before any DB query) ───────────────────────────

    # 1. Non-empty
    if not new_labels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="branch_labels must not be empty",
        )

    # 2. No duplicates (case-sensitive)
    seen: Set[str] = set()
    for label in new_labels:
        if label in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate label: {label!r}",
            )
        seen.add(label)

    # 3. Length cap
    too_long = [lbl for lbl in new_labels if len(lbl) > _MAX_LABEL_LENGTH]
    if too_long:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Labels must be ≤ {_MAX_LABEL_LENGTH} characters. "
                f"Offending: {too_long}"
            ),
        )

    # ── Fetch current labels ──────────────────────────────────────────────────
    org = session.get(Organization, staff.org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    current_labels: Set[str] = set(org.branch_labels)
    incoming_labels: Set[str] = set(new_labels)
    removed_labels: Set[str] = current_labels - incoming_labels

    # ── In-use check (real DB query, not trust-the-caller) ───────────────────
    # Query for ALL removed labels in a single round-trip.  If *any* of them
    # are referenced by an existing submission the whole request is rejected.
    if removed_labels:
        in_use = session.scalars(
            select(Submission.branch)
            .where(Submission.org_id == staff.org_id)
            .where(Submission.branch.in_(removed_labels))
            .distinct()
        ).all()

        if in_use:
            labels_str = ", ".join(f'"{label}"' for label in sorted(in_use))
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot remove {labels_str}. This branch is still "
                    "referenced by existing submissions. Please move those submissions "
                    "to a different branch first, then try again."
                ),
            )

    # ── Write — only reached if all checks pass ───────────────────────────────
    org.branch_labels = new_labels
    session.commit()

    return BranchLabelsResponse(branch_labels=new_labels)
