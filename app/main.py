"""
app/main.py
───────────
FastAPI application entry point.

/docs and /redoc are enabled in every environment except production
(i.e. when ENV != "production").  Set ENV=production in your deployment
environment to suppress the interactive docs.
"""

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.jobs import start_jobs, shutdown_jobs

limiter = Limiter(key_func=get_remote_address)

_docs_url = None if settings.ENV == "production" else "/docs"
_redoc_url = None if settings.ENV == "production" else "/redoc"
_openapi_url = None if settings.ENV == "production" else "/openapi.json"

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_jobs()
    yield
    shutdown_jobs()

app = FastAPI(
    title="Tapply API",
    version="0.1.0",
    description="Multi-tenant SaaS backend for Tapply.",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

allowed_origins = [url.strip() for url in settings.FRONTEND_URLS.split(",") if url.strip()]
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


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

from app.api.routers import organizations, stands, tap, submissions, cards, staff

app.include_router(organizations.router)
app.include_router(stands.router)
app.include_router(tap.router)
app.include_router(submissions.router)
app.include_router(cards.router)
app.include_router(staff.router)

