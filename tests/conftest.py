from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_DATA_DIR = Path(".data") / "tests"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Shared only within the current pytest process (not across runs/processes).
_SESSION_DB_DIR = Path(tempfile.mkdtemp(prefix="autohunter_pytest_", dir=_DATA_DIR))
_SQLITE_URL = f"sqlite+pysqlite:///{(_SESSION_DB_DIR / 'autohunter_test.db').as_posix()}?check_same_thread=false"
os.environ.setdefault("DATABASE_URL", _SQLITE_URL)
# pytest-xdist: os workers herdam o DATABASE_URL do processo principal; com um unico arquivo
# SQLite compartilhado, o drop_all/create_all de um worker apaga as tabelas dos outros
# ("no such table"). Cada worker usa o proprio arquivo (nao mexe em URLs que nao sao SQLite).
if os.environ.get("PYTEST_XDIST_WORKER") and os.environ["DATABASE_URL"].startswith("sqlite"):
    os.environ["DATABASE_URL"] = _SQLITE_URL

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
os.environ.setdefault("FB_PROFILE_BASE_DIR", str(_DATA_DIR / "runtime" / "fb_profiles"))
os.environ.setdefault("FB_DEBUG_BASE_DIR", str(_DATA_DIR / "runtime" / "fb_debug"))

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


# No SQLite a coluna ARRAY vira TEXT, mas o sqlite3 nao aceita `list` como parametro. Serializa
# como JSON na ida e desserializa na volta, para que log()/emit_event() (tags=[...]) rodem de
# verdade nos testes em vez de serem trocados por monkeypatch.
import json as _json

_orig_array_bind = ARRAY.bind_processor
_orig_array_result = ARRAY.result_processor


def _array_bind_processor(self, dialect):
    if dialect.name == "postgresql":
        return _orig_array_bind(self, dialect)
    return lambda value: None if value is None else _json.dumps(list(value))


def _array_result_processor(self, dialect, coltype):
    if dialect.name == "postgresql":
        return _orig_array_result(self, dialect, coltype)
    return lambda value: _json.loads(value) if isinstance(value, str) else value


ARRAY.bind_processor = _array_bind_processor
ARRAY.result_processor = _array_result_processor


# Postgres accepts a plain string for a UUID column bind (e.g. an id parsed straight out of
# Telegram callback_data). SQLite's fallback Uuid processor requires an actual uuid.UUID
# instance, so code paths comparing a UUID column to a raw string can't be exercised against
# the test DB without this. Widen the bind processor to accept both, matching Postgres behavior.
_orig_uuid_bind_processor = UUID.bind_processor


def _uuid_bind_processor_accepting_str(self, dialect):
    inner = _orig_uuid_bind_processor(self, dialect)
    if dialect.name == "postgresql" or not self.as_uuid or inner is None:
        return inner

    import uuid as _uuid_mod

    def process(value):
        if value is not None and not isinstance(value, _uuid_mod.UUID):
            value = _uuid_mod.UUID(str(value))
        return inner(value)

    return process


UUID.bind_processor = _uuid_bind_processor_accepting_str


from app.db.base import Base
from app.db.deps import get_db
from app.db.session import SessionLocalHTTP, engine
from app.core.settings import settings


_SCHEMA_READY = False


def _recreate_schema() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _truncate_all_tables() -> None:
    """Esvazia todas as tabelas (ordem inversa das FKs) sem refazer o DDL."""
    from sqlalchemy import text

    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        # sqlite_sequence so existe se alguma tabela usa AUTOINCREMENT (e so depois do 1o insert).
        if conn.execute(text("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'")).first():
            conn.execute(text("DELETE FROM sqlite_sequence"))


@pytest.fixture(autouse=True)
def _reset_db(request: pytest.FixtureRequest):
    # Antes: drop_all+create_all de ~31 tabelas em CADA teste (~0,7s de setup x 2.300 testes).
    # Agora o schema e criado uma vez por processo e cada teste so limpa as linhas.
    global _SCHEMA_READY
    if request.node.get_closest_marker("postgres"):
        yield
        return
    if not _SCHEMA_READY:
        _recreate_schema()
        _SCHEMA_READY = True
    else:
        try:
            _truncate_all_tables()
        except Exception:
            # Um teste pode ter alterado o schema (drop_all/create_all proprio): recria do zero.
            _recreate_schema()
    yield


@pytest.fixture(autouse=True)
def _reset_log_throttle():
    from app.services import system_logs_service

    system_logs_service._throttle_last.clear()
    yield


@pytest.fixture(autouse=True)
def _force_fb_test_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fb_profiles = tmp_path / "fb_profiles"
    fb_debug = tmp_path / "fb_debug"
    fb_profiles.mkdir(parents=True, exist_ok=True)
    fb_debug.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FB_PROFILE_BASE_DIR", str(fb_profiles))
    monkeypatch.setenv("FB_DEBUG_BASE_DIR", str(fb_debug))
    monkeypatch.setattr(settings, "fb_profile_base_dir", str(fb_profiles))
    monkeypatch.setattr(settings, "fb_debug_base_dir", str(fb_debug))


@pytest.fixture()
def db():
    # SessionLocalHTTP (sem guarda de thread): esta fixture é reaproveitada pela
    # fixture `client` como a Session de Depends(get_db), e o TestClient despacha
    # dependências síncronas via threadpool — podendo trocar de thread entre
    # chamadas. Uma ThreadSafeSession dispararia o guard de thread cruzada nesse
    # cenário (ver app/db/deps.py para o equivalente de produção).
    session = SessionLocalHTTP()
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
