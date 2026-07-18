from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import set_org_context
from app.api.deps import get_db
from app.schemas import TapContextResponse, TapSubmissionCreate
import json

router = APIRouter(prefix="/tap", tags=["tap"])

# We import the limiter from main, but since it's attached to request.app.state.limiter we can use a decorator
# Alternatively, we can use dependency injection or direct decorator if we get a reference to the limiter.
# The standard slowapi pattern is to import the limiter and use it as a decorator.
from app.main import limiter

MAX_PAYLOAD_SIZE = 50 * 1024  # 50KB

async def verify_payload_size(request: Request):
    """
    Dependency to verify payload size doesn't exceed MAX_PAYLOAD_SIZE.
    We check Content-Length header. If missing, we still read the body and limit it.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_PAYLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Payload too large",
        )
    # Also enforce strictly by reading
    body = await request.body()
    if len(body) > MAX_PAYLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Payload too large",
        )
    return body

def _resolve_context(session: Session, token: str):
    row = session.execute(
        text("SELECT org_id, stand_id, default_branch, form_fields FROM auth.resolve_card_context(:token)"),
        {"token": token},
    ).one_or_none()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")
    
    return row

@router.get("/{token}", response_model=TapContextResponse)
@limiter.limit("30/minute")
def get_tap_context(request: Request, token: str, session: Session = Depends(get_db)):
    row = _resolve_context(session, token)
    return TapContextResponse(
        form_fields=row.form_fields,
        default_branch=row.default_branch
    )

@router.post("/{token}/submit", status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def submit_tap(
    request: Request,
    token: str,
    payload: TapSubmissionCreate,
    session: Session = Depends(get_db),
    _ = Depends(verify_payload_size)
):
    if not payload.consent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Consent is required")

    row = _resolve_context(session, token)
    
    # Validate payload data against form schema
    # Basic required-field presence check as per requirements
    required_fields = []
    if isinstance(row.form_fields, list):
        for field in row.form_fields:
            if field.get("required", False):
                required_fields.append(field.get("name"))
    
    for req_field in required_fields:
        if req_field not in payload.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {req_field}"
            )

    # Branch precedence: explicit client branch over default_branch
    branch = payload.data.get("branch", row.default_branch)

    # Set context before INSERT to satisfy RLS WITH CHECK policy
    set_org_context(session, row.org_id)

    # Insert submission
    session.execute(
        text("""
            INSERT INTO submissions (card_id, org_id, status, branch, data)
            VALUES (
                (SELECT id FROM cards WHERE token = :token),
                :org_id,
                'to_contact',
                :branch,
                :data
            )
        """),
        {
            "token": token,
            "org_id": row.org_id,
            "branch": branch,
            "data": json.dumps(payload.data)
        }
    )
    session.commit()
    return {"status": "ok"}
