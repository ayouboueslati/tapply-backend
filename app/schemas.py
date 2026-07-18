from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime

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
