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
    is_active: bool
    assigned_recruiter_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)

class CardUpdate(BaseModel):
    is_active: Optional[bool] = None
    assigned_recruiter_id: Optional[UUID] = None

class TapContextResponse(BaseModel):
    org_name: str
    form_fields: list[dict]
    default_branch: str | None
    logo_url: str | None = None
    theme_color: str = "#C9A96E"
    welcome_title: str = "Choose Your Path"
    welcome_text: str = "Find the programme that ignites your ambition."

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


# ── Branding ─────────────────────────────────────────────────────────────────

class BrandingResponse(BaseModel):
    """Response for GET /organizations/me/branding."""
    logo_url: Optional[str]
    theme_color: str
    welcome_title: str
    welcome_text: str

    model_config = ConfigDict(from_attributes=True)


class BrandingUpdate(BaseModel):
    """
    Request body for PATCH /organizations/me/branding.
    All fields optional — only supplied fields are updated.
    """
    logo_url: Optional[str] = None
    theme_color: Optional[str] = None
    welcome_title: Optional[str] = None
    welcome_text: Optional[str] = None


# ── Form Schema ───────────────────────────────────────────────────────────────

class FormSchemaResponse(BaseModel):
    """Response for GET /organizations/me/form-schema."""
    fields: list[dict]


class FormSchemaUpdate(BaseModel):
    """
    Request body for PATCH /organizations/me/form-schema.
    Replaces the entire fields array.
    Each field must be a dict with at least {name, type}.
    """
    fields: list[dict]


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
    assigned_to: Optional[UUID] = None
    score: Optional[int] = None
    notes: Optional[list] = None
    is_duplicate: Optional[bool] = None


class SubmissionResponse(BaseModel):
    """Single submission row returned by GET /submissions and PATCH /submissions/{id}."""
    id: UUID
    card_id: UUID
    org_id: UUID
    status: str
    branch: Optional[str]
    data: dict
    assigned_to: Optional[UUID] = None
    score: Optional[int] = None
    notes: list
    is_duplicate: bool
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

