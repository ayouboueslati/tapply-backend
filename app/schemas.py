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

class TapContextResponse(BaseModel):
    form_fields: list[dict]
    default_branch: str | None

class TapSubmissionCreate(BaseModel):
    consent: bool
    data: dict

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
