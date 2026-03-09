from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.source_run import SourceRun
from app.services.source_runs_service import record_run


def _last_success_at(db, source: str):
    row = (
        db.query(SourceRun)
        .filter(SourceRun.source == source)
        .filter(SourceRun.status == "success")
        .order_by(SourceRun.created_at.desc())
        .first()
    )
    return row.created_at if row else None


def test_skip_error_blocked_do_not_advance_last_success_at(db):
    record_run(db, source="olx", kind="scheduler", status="success")
    db.commit()
    baseline = _last_success_at(db, "olx")
    assert baseline is not None

    record_run(db, source="olx", kind="scheduler", status="skipped")
    record_run(db, source="olx", kind="scheduler", status="error")
    record_run(db, source="olx", kind="scheduler", status="blocked")
    db.commit()

    assert _last_success_at(db, "olx") == baseline


def test_success_advances_last_success_at(db):
    record_run(db, source="ml", kind="scheduler", status="success")
    db.commit()
    first = _last_success_at(db, "ml")

    row = SourceRun(source="ml", kind="scheduler", status="success")
    row.created_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    db.add(row)
    db.commit()

    second = _last_success_at(db, "ml")
    assert second is not None
    assert first is not None
    assert second > first
