from __future__ import annotations

import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Test environment (must be set BEFORE importing app.* modules)
# ---------------------------------------------------------------------------

# Use a local SQLite file for fast, deterministic tests (no Postgres required).
_DATA_DIR = Path(".data") / "tests"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite+pysqlite:///{(_DATA_DIR / 'autohunter_test.db').as_posix()}?check_same_thread=false",
)

# Ensure API won't start schedulers/browser in tests.
os.environ.setdefault("ENABLE_SCHEDULER_IN_API", "false")
os.environ.setdefault("ENABLE_PLAYWRIGHT", "false")

# Keep OLX health file isolated per test run.
os.environ.setdefault("OLX_HEALTH_PATH", str(_DATA_DIR / "olx_health.json"))


# ---------------------------------------------------------------------------
# SQLite compatibility for Postgres-specific SQLAlchemy types
# ---------------------------------------------------------------------------

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    # Store JSONB as TEXT for SQLite test runs.
    return "TEXT"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001
    # Use a plain char field; UUID type will still bind/process UUID values.
    return "CHAR(36)"


# Now it is safe to import app modules.
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.db.deps import get_db


@pytest.fixture(autouse=True)
def _reset_db():
    """Hard reset DB per test.

    Simple and reliable. The schema is small enough that this stays fast on
    Raspberry Pi 3, and it avoids flaky transactional tricks around commits.
    """

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    from app.main import app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
