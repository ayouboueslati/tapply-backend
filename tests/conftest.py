"""
tests/conftest.py
─────────────────
Pytest fixtures for the Tapply RLS test suite.

Requirements:
  - A PostgreSQL database with migrations applied (alembic upgrade head).
  - The database URL must be set in TEST_DATABASE_URL (or DATABASE_URL).
  - The connection must use a SUPERUSER role so that:
      a) Direct INSERTs for test setup bypass FORCE RLS.
      b) SET ROLE tapply_app works within the same connection.
  - The tapply_app role must exist for privilege-boundary tests (created by
    scripts/create_roles.sql).  Tests that require tapply_app skip gracefully
    if the role is missing.

Isolation strategy:
  Each test function gets a fresh database connection.  All test data is
  created inside a single transaction that is ROLLED BACK at teardown — no
  test data persists in the database between test runs.
"""

import os

import psycopg2
import pytest
from dotenv import load_dotenv

load_dotenv()


def _get_test_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "Set TEST_DATABASE_URL (or DATABASE_URL) before running the test suite."
        )
    return url


@pytest.fixture(scope="function")
def owner_conn():
    """
    A psycopg2 connection opened as the superuser (from TEST_DATABASE_URL).

    - autocommit is OFF so all statements run inside an implicit transaction.
    - The transaction is rolled back at teardown regardless of test outcome,
      ensuring no test data leaks between tests.
    - The connection remains in error state after an expected exception; the
      rollback in teardown handles cleanup automatically.
    """
    conn = psycopg2.connect(_get_test_url())
    conn.autocommit = False
    yield conn
    # Teardown: roll back to clean up any test data inserted during the test.
    try:
        conn.rollback()
    finally:
        conn.close()


@pytest.fixture(scope="function")
def tapply_app_exists(owner_conn) -> bool:
    """Returns True if the tapply_app role exists in the database."""
    cur = owner_conn.cursor()
    cur.execute("SELECT EXISTS(SELECT FROM pg_roles WHERE rolname = 'tapply_app')")
    return bool(cur.fetchone()[0])
