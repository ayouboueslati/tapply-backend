"""
app/db/base.py
──────────────
SQLAlchemy declarative base shared by all ORM models.

All models import ``Base`` from here so that ``Base.metadata`` is a single
object that Alembic's env.py can reference for autogenerate support.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all Tapply ORM models."""
