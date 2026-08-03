from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import List, Optional

class OrganizationCreate(BaseModel):
    name: str

class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    billing_status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class StaffContextResponse(BaseModel):
    email: str
    org_name: str
    role: str
    form_fields: list[dict]

class StandCreate(BaseModel):
    name: str
    default_branch: str | None = None

class StandUpdate(BaseModel):
    name: str | None = None
    default_branch: str | None = None

class StandResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    default_branch: str | None
    
    model_config = ConfigDict(from_attributes=True)


class CardResponse(BaseModel):
    """Card returned by GET /cards — exposes the tap token so staff can share tap links."""
    id: UUID
    stand_id: UUID
    stand_name: str   # denormalized from the joined Stand for display convenience
    token: str

    model_config = ConfigDict(from_attributes=True)

class TapContextResponse(BaseModel):
    org_name: str
    form_fields: list[dict]
    default_branch: str | None

class TapSubmissionCreate(BaseModel):
    idempotency_key: UUID
    consent: bool
    data: dict

class TapSubmissionResponse(BaseModel):
    status: str
    submission_id: UUID

# ── Step 4: Status labels ─────────────────────────────────────────────────────

class StatusLabelsResponse(BaseModel):
    """Response body for GET /organizations/me/status-labels."""
    status_labels: List[str]

    model_config = ConfigDict(from_attributes=True)


class StatusLabelsUpdate(BaseModel):
    """
    Request body for PATCH /organizations/me/status-labels.

    Validation rules (enforced before any DB query):
    - List must be non-empty.
    - No duplicate entries (case-sensitive).
    - Each label must be ≤ 50 characters (dashboard-facing display text).

    Rename semantics: removing label X and adding label Y is permitted only
    when no existing submission references X. If any submission still uses X,
    the entire request is rejected with 409. Migrate affected submissions
    first, then rename.
    """
    status_labels: List[str]


class BranchLabelsResponse(BaseModel):
    """Response body for GET /organizations/me/branches."""
    branch_labels: List[str]

    model_config = ConfigDict(from_attributes=True)


class BranchLabelsUpdate(BaseModel):
    """
    Request body for PATCH /organizations/me/branches.

    Validation rules mirror status_labels exactly:
    - List must be non-empty.
    - No duplicate entries (case-sensitive).
    - Each label must be ≤ 50 characters.

    Orphan protection: like status labels, removing a branch label currently
    assigned to any submission is rejected with 409.
    """
    branch_labels: List[str]


# ── Step 4: Submission read / update ─────────────────────────────────────────

class SubmissionUpdate(BaseModel):
    """
    Request body for PATCH /submissions/{id}.

    Both fields are optional — at least one should be provided (a no-op
    request with neither field is accepted but does nothing).

    ``status`` is validated against the org's current ``status_labels`` list
    at the application level (not enforced by the DB).  Invalid values → 400.

    ``branch`` accepts any non-empty string with no further validation —
    consistent with how candidates submit it in Step 3.
    """
    status: Optional[str] = None
    branch: Optional[str] = None


class SubmissionResponse(BaseModel):
    """Single submission row returned by GET /submissions and PATCH /submissions/{id}."""
    id: UUID
    card_id: UUID
    org_id: UUID
    status: str
    branch: Optional[str]
    data: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubmissionListResponse(BaseModel):
    """Paginated response for GET /submissions."""
    items: List[SubmissionResponse]
    total: int
    limit: int
    offset: int


# ── Step 12: Staff / Team management ─────────────────────────────────────────

class StaffMemberResponse(BaseModel):
    id: UUID
    email: str
    role: str
    can_edit: bool
    can_edit_until: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StaffPermissionUpdate(BaseModel):
    can_edit: bool
    can_edit_until: Optional[datetime] = None

