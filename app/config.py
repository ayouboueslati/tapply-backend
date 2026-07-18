"""
app/config.py
─────────────
Application settings loaded from environment variables / .env file.

All database connections use DATABASE_URL at runtime (tapply_app role).
Alembic migrations use MIGRATION_DATABASE_URL (superuser) — see alembic/env.py.
"""

import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    # Primary connection — tapply_app role, RLS enforced.
    DATABASE_URL: str

    # Superuser URL used by Alembic env.py when running migrations.
    # Falls back to DATABASE_URL if not set (fine for development where the
    # developer connects as a superuser).
    MIGRATION_DATABASE_URL: str = ""

    # Separate DB for the test suite.  Must have migrations already applied.
    TEST_DATABASE_URL: str = ""

    # Clerk backend API key
    CLERK_SECRET_KEY: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
