from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError

from app.services import scrape_jobs_service as svc


class _FakeResult:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _CaptureDB:
    def __init__(self, *, rowcount: int = 1):
        self.captured_stmt = None
        self._rowcount = rowcount

    def execute(self, stmt):
        self.captured_stmt = stmt
        return _FakeResult(self._rowcount)


class _ProgrammingErrorDB:
    def __init__(self):
        self.rollback_called = False

    def execute(self, stmt):
        orig = Exception("there is no unique or exclusion constraint matching the ON CONFLICT specification")
        raise ProgrammingError("INSERT ...", {}, orig)

    def rollback(self):
        self.rollback_called = True

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _PgIndexDefDB:
    def __init__(self, rows):
        self._rows = rows

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def execute(self, _stmt):
        return _RowsResult(self._rows)


def test_enqueue_job_builds_expected_on_conflict_target(monkeypatch):
    db = _CaptureDB(rowcount=1)

    monkeypatch.setattr(svc, "requeue_stale_running_jobs", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(svc, "count_active_jobs", lambda *_args, **_kwargs: 0)

    inserted = svc.enqueue_job(db, source="olx", queue="browser")

    assert inserted is True
    sql = str(
        db.captured_stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "ON CONFLICT (source, queue)" in sql
    assert "WHERE status IN ('queued','running')" in sql
    assert "DO NOTHING" in sql


def test_enqueue_job_wraps_missing_conflict_constraint_with_details(monkeypatch):
    db = _ProgrammingErrorDB()

    monkeypatch.setattr(svc, "requeue_stale_running_jobs", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(svc, "count_active_jobs", lambda *_args, **_kwargs: 0)

    with pytest.raises(RuntimeError) as exc:
        svc.enqueue_job(db, source="mercadolivre", queue="browser")

    msg = str(exc.value)
    assert "scrape_jobs enqueue schema mismatch" in msg
    assert "ON CONFLICT (source, queue)" in msg
    assert "status IN ('queued','running')" in msg


def test_scrape_jobs_base_migration_has_matching_partial_unique_index():
    with open("migrations/versions/fase1_003_scrape_jobs_queue.py", encoding="utf-8") as f:
        migration = f.read()

    assert "uq_scrape_jobs_active_source_queue" in migration
    assert "[\"source\", \"queue\"]" in migration
    assert "status IN ('queued','running')" in migration


def test_enqueue_job_rolls_back_before_schema_introspection(monkeypatch):
    db = _ProgrammingErrorDB()

    monkeypatch.setattr(svc, "requeue_stale_running_jobs", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(svc, "count_active_jobs", lambda *_args, **_kwargs: 0)

    with pytest.raises(RuntimeError):
        svc.enqueue_job(db, source="olx", queue="browser")

    assert db.rollback_called is True


def test_has_active_source_queue_partial_index_guard_detects_sqlite_partial_index(db):
    db.execute(svc.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_scrape_jobs_active_source_queue_unique
        ON scrape_jobs (source, queue)
        WHERE status IN ('queued','running')
    """))
    db.commit()

    assert svc.has_active_source_queue_partial_index(db) is True
    details = svc.get_active_source_queue_partial_index_details(db)
    assert details["ok"] is True
    assert details["index_name_ok"] is True


def test_has_active_source_queue_partial_index_guard_accepts_postgres_any_array_format():
    db = _PgIndexDefDB(
        rows=[
            (
                "ix_scrape_jobs_active_source_queue_unique",
                "CREATE UNIQUE INDEX ix_scrape_jobs_active_source_queue_unique ON public.scrape_jobs USING btree (source, queue) "
                "WHERE ((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying])::text[]))",
            )
        ]
    )

    assert svc.has_active_source_queue_partial_index(db) is True
    details = svc.get_active_source_queue_partial_index_details(db)
    assert details["ok"] is True
    assert details["index_name"] == "ix_scrape_jobs_active_source_queue_unique"
    assert details["index_name_ok"] is True
