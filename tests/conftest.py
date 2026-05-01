from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_DATA_DIR = Path(".data") / "tests"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Shared only within the current pytest process (not across runs/processes).
_SESSION_DB_DIR = Path(tempfile.mkdtemp(prefix="autohunter_pytest_", dir=_DATA_DIR))
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite+pysqlite:///{(_SESSION_DB_DIR / 'autohunter_test.db').as_posix()}?check_same_thread=false",
)

os.environ.setdefault("ENABLE_SCHEDULER_IN_API", "false")
os.environ.setdefault("ENABLE_PLAYWRIGHT", "false")
os.environ.setdefault("RUNTIME_STATE_DIR", str(_DATA_DIR / "runtime" / "state"))
os.environ.setdefault("RUNTIME_CACHE_DIR", str(_DATA_DIR / "runtime" / "cache"))
os.environ.setdefault("RUNTIME_LOG_DIR", str(_DATA_DIR / "runtime" / "log"))
os.environ.setdefault("HEALTH_STATE_DIR", str(_DATA_DIR / "runtime" / "state" / "health"))
os.environ.setdefault("PLAYWRIGHT_STORAGE_DIR", str(_DATA_DIR / "runtime" / "state" / "playwright"))
os.environ.setdefault("SOURCE_AUDIT_ROOT", str(_DATA_DIR / "runtime" / "cache" / "artifacts" / "source_audit_candidates"))
os.environ.setdefault("PLAYWRIGHT_BROWSERS_DIR", str(_DATA_DIR / "runtime" / "cache" / "pw-browsers"))
os.environ.setdefault("OLX_HEALTH_PATH", str(_DATA_DIR / "olx_health.json"))

from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):
    return "TEXT"


from app.db.base import Base
from app.db.deps import get_db
from app.db.session import SessionLocal, engine


@pytest.fixture(autouse=True)
def _reset_db(request: pytest.FixtureRequest):
    if request.node.get_closest_marker("postgres"):
        yield
        return
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
    from fastapi.testclient import TestClient
    from app.main import app

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def pytest_configure(config):
    config.addinivalue_line("markers", "postgres: requires TEST_DATABASE_URL (PostgreSQL integration tests)")


def pytest_collection_modifyitems(config, items):
    if os.getenv("TEST_DATABASE_URL"):
        return
    skip_postgres = pytest.mark.skip(reason="requires TEST_DATABASE_URL for PostgreSQL integration tests")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip_postgres)
