from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import set_org_context
from app.api.deps import get_db
from app.schemas import TapContextResponse, TapSubmissionCreate, TapSubmissionResponse
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
        text("SELECT org_id, stand_id, default_branch, form_fields, org_name FROM auth.resolve_card_context(:token)"),
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
        org_name=row.org_name,
        form_fields=row.form_fields,
        default_branch=row.default_branch
    )

@router.post("/{token}/submit", response_model=TapSubmissionResponse)
@limiter.limit("30/minute")
def submit_tap(
    request: Request,
    token: str,
    payload: TapSubmissionCreate,
    response: Response,
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
    result = session.execute(
        text("""
            INSERT INTO submissions (card_id, org_id, status, branch, data, idempotency_key)
            VALUES (
                (SELECT id FROM cards WHERE token = :token),
                :org_id,
                'to_contact',
                :branch,
                :data,
                :idempotency_key
            )
            ON CONFLICT (org_id, idempotency_key) DO UPDATE SET id = submissions.id
            RETURNING id, (xmax = 0) AS inserted
        """),
        {
            "token": token,
            "org_id": row.org_id,
            "branch": branch,
            "data": json.dumps(payload.data),
            "idempotency_key": str(payload.idempotency_key)
        }
    )
    
    # xmax = 0 means this row was just inserted by this transaction, not an existing row 
    # touched by the ON CONFLICT UPDATE — this is how we distinguish a genuine new submission 
    # from an idempotent retry.
    inserted_row = result.one()
    submission_id = inserted_row.id
    inserted = inserted_row.inserted
    
    session.commit()
    
    if inserted:
        response.status_code = status.HTTP_201_CREATED
    else:
        response.status_code = status.HTTP_200_OK
        
    return {"status": "ok", "submission_id": submission_id}
