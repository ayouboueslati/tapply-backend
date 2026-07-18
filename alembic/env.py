"""
alembic/env.py
──────────────
Alembic migration environment configuration for Tapply.

Database URL precedence (highest to lowest):
  1. MIGRATION_DATABASE_URL env var  — superuser, recommended for CI/CD
  2. DATABASE_URL env var            — falls back if MIGRATION_DATABASE_URL unset

The application's runtime role (``tapply_app``) must NOT own the tables, so
migrations should always run as a superuser or a role with DDL privileges.

Models are imported via ``app.models`` to populate ``Base.metadata`` for
Alembic's autogenerate support.  Add new models to ``app/models/__init__.py``
to keep them visible here.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Make the project root importable ─────────────────────────────────────────
# alembic.ini sets prepend_sys_path = . which adds the project root to sys.path
# when Alembic is run from the project root directory.  The explicit insert
# below is a defensive fallback for environments that skip alembic.ini.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv()

# ── Import all models so Base.metadata is fully populated ────────────────────
from app.db.base import Base
import app.models  # noqa: F401 — side-effect: registers all models with Base

# ── Alembic Config object ─────────────────────────────────────────────────────
config = context.config

# Resolve the migration URL (superuser preferred).
migration_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get(
    "DATABASE_URL"
)
if not migration_url:
    raise RuntimeError(
        "No database URL found.  Set MIGRATION_DATABASE_URL (or DATABASE_URL) "
        "before running Alembic."
    )
config.set_main_option("sqlalchemy.url", migration_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ── Offline migration (generate SQL script without a live connection) ─────────
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include JSONB, UUID, etc. in autogenerate comparisons.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migration (run against a live database connection) ─────────────────
def run_migrations_online() -> None:
    """Run migrations in 'online' mode against an active database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No pooling in migration runner.
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
