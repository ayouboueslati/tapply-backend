"""
app/main.py
───────────
FastAPI application entry point for Step 1.

Only one endpoint is exposed: GET /health.
Authentication, public form endpoints, and admin APIs are added in later steps.
"""

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Tapply API",
    version="0.1.0",
    description="Multi-tenant SaaS backend for Tapply.",
    # Docs disabled until auth is in place (Step 2).
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.get(
    "/health",
    summary="Health check",
    tags=["infra"],
    response_model=dict,
)
def health_check() -> dict:
    """
    Returns ``{"status": "ok"}`` when the server is up.

    This endpoint is intentionally unauthenticated and does not touch the
    database — it is safe to use as a load-balancer / readiness probe target.
    """
    return {"status": "ok"}

from app.api.routers import organizations, stands, tap

app.include_router(organizations.router)
app.include_router(stands.router)
app.include_router(tap.router)

