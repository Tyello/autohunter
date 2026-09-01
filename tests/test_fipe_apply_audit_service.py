from __future__ import annotations

from app.models.system_log import SystemLog
from app.services.fipe_apply_audit_service import log_fipe_apply_plan_run


class _DBSessionWrapper:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, exc_type, exc, tb):
        return False


def test_logs_dry_run_message(monkeypatch, db):
    monkeypatch.setattr("app.services.fipe_apply_audit_service.SessionLocal", lambda: _DBSessionWrapper(db))

    log_fipe_apply_plan_run(
        reference_month="2026-01",
        limit=100,
        dry_run=True,
        planned_inserts_count=5,
        would_update_count=2,
        inserted_count=0,
        updated_count=0,
        skipped_counts={"missing_fipe": 3},
        sample_size=10,
    )

    row = db.query(SystemLog).filter(SystemLog.component == "fipe_apply_plan").one()
    assert row.message == "fipe apply plan dry-run"
    assert row.level == "info"
    assert row.payload["skipped_counts"] == {"missing_fipe": 3}


def test_logs_live_message_when_not_dry_run(monkeypatch, db):
    monkeypatch.setattr("app.services.fipe_apply_audit_service.SessionLocal", lambda: _DBSessionWrapper(db))

    log_fipe_apply_plan_run(
        reference_month="2026-01",
        limit=100,
        dry_run=False,
        planned_inserts_count=5,
        would_update_count=2,
        inserted_count=5,
        updated_count=2,
        skipped_counts=None,
        sample_size=10,
    )

    row = db.query(SystemLog).filter(SystemLog.component == "fipe_apply_plan").one()
    assert row.message == "fipe apply plan live"
    assert row.payload["skipped_counts"] == {}


def test_logs_error_message_with_error_level(monkeypatch, db):
    monkeypatch.setattr("app.services.fipe_apply_audit_service.SessionLocal", lambda: _DBSessionWrapper(db))

    log_fipe_apply_plan_run(
        reference_month="2026-01",
        limit=100,
        dry_run=True,
        planned_inserts_count=0,
        would_update_count=0,
        inserted_count=0,
        updated_count=0,
        skipped_counts=None,
        sample_size=0,
        error="boom",
    )

    row = db.query(SystemLog).filter(SystemLog.component == "fipe_apply_plan").one()
    assert row.message == "fipe apply plan error"
    assert row.level == "error"
    assert row.payload["error"] == "boom"


def test_swallows_exceptions_from_session(monkeypatch, db):
    def _raise():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.services.fipe_apply_audit_service.SessionLocal", _raise)

    log_fipe_apply_plan_run(
        reference_month="2026-01",
        limit=100,
        dry_run=True,
        planned_inserts_count=0,
        would_update_count=0,
        inserted_count=0,
        updated_count=0,
        skipped_counts=None,
        sample_size=0,
    )
