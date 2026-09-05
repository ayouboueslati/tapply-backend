import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, BackgroundTasks
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import set_org_context
from app.api.deps import get_db
from app.schemas import TapContextResponse, TapSubmissionCreate, TapSubmissionResponse
import json

logger = logging.getLogger(__name__)
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
        text("SELECT org_id, stand_id, default_branch, form_fields, org_name, branch_labels, logo_url, theme_color, welcome_title, welcome_text, is_active, assigned_recruiter_id FROM auth.resolve_card_context(:token)"),
        {"token": token},
    ).one_or_none()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")
        
    if not row.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This card has been deactivated.")
    
    return row

@router.get("/{token}", response_model=TapContextResponse)
@limiter.limit("30/minute")
def get_tap_context(request: Request, token: str, session: Session = Depends(get_db)):
    row = _resolve_context(session, token)
    
    # Inject dynamic branch labels if they exist
    form_fields = row.form_fields
    if isinstance(form_fields, list) and row.branch_labels:
        for field in form_fields:
            if field.get("name") == "branch":
                field["options"] = row.branch_labels

    return TapContextResponse(
        org_name=row.org_name,
        form_fields=form_fields,
        default_branch=row.default_branch,
        logo_url=row.logo_url,
        theme_color=row.theme_color,
        welcome_title=row.welcome_title,
        welcome_text=row.welcome_text,
    )

@router.post("/{token}/submit", response_model=TapSubmissionResponse)
@limiter.limit("30/minute")
def submit_tap(
    request: Request,
    token: str,
    payload: TapSubmissionCreate,
    response: Response,
    background_tasks: BackgroundTasks,
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

    # Duplicate submission check by email within 5 minutes
    email = payload.data.get("email")
    if email:
        duplicate = session.execute(
            text("""
                SELECT id FROM submissions
                WHERE org_id = :org_id
                  AND data->>'email' = :email
                  AND created_at >= NOW() - INTERVAL '5 minutes'
                LIMIT 1
            """),
            {"org_id": row.org_id, "email": email}
        ).one_or_none()
        
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="You have already submitted this form recently. Please wait a few minutes before trying again."
            )

    # Set context before INSERT to satisfy RLS WITH CHECK policy
    set_org_context(session, row.org_id)

    # Insert submission
    result = session.execute(
        text("""
            INSERT INTO submissions (card_id, org_id, status, branch, data, idempotency_key, assigned_to)
            VALUES (
                (SELECT id FROM cards WHERE token = :token),
                :org_id,
                'to_contact',
                :branch,
                :data,
                :idempotency_key,
                :assigned_to
            )
            ON CONFLICT (org_id, idempotency_key) DO UPDATE SET id = submissions.id
            RETURNING id, (xmax = 0) AS inserted
        """),
        {
            "token": token,
            "org_id": row.org_id,
            "branch": branch,
            "data": json.dumps(payload.data),
            "idempotency_key": str(payload.idempotency_key),
            "assigned_to": row.assigned_recruiter_id
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
        # Enqueue the confirmation email task
        if email:
            background_tasks.add_task(
                send_confirmation_email,
                email,
                row.org_name,
                row.org_id
            )
    else:
        response.status_code = status.HTTP_200_OK
        
    return {"status": "ok", "submission_id": submission_id}

# Stub for Phase 1 email integration
def send_confirmation_email(to_email: str, org_name: str, org_id: str):
    """
    Sends a confirmation email using Resend.
    Currently stubbed out until the Resend API key is configured.
    """
    logger.info(f"[Resend stub] Sending confirmation email to {to_email} for org {org_name}")
    # TODO: Implement actual Resend SDK call here
    # import resend
    # resend.api_key = os.environ["RESEND_API_KEY"]
    # resend.Emails.send({
    #     "from": f"{org_name} <hello@tapply.io>",
    #     "to": [to_email],
    #     "subject": f"Thanks for connecting with {org_name}",
    #     "html": f"<p>Hi there, thanks for tapping our card!</p>"
    # })
