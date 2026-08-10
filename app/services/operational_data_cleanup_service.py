from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings

BATCH_SIZE = 1000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cut(days: int) -> datetime:
    return _utcnow() - timedelta(days=max(1, int(days)))


def _cut_hours(hours: int) -> datetime:
    return _utcnow() - timedelta(hours=max(1, int(hours)))


def _delete_in_batches(db: Session, sql: str, params: dict) -> int:
    total = 0
    while True:
        n = int(db.execute(text(sql), params).rowcount or 0)
        if n <= 0:
            break
        total += n
        db.commit()
        if n < BATCH_SIZE:
            break
    return total


def unprotected_cleanup_rules() -> list[tuple[str, str, dict]]:
    """DELETE rules for tables with no core-data guardrail.

    Excludes `notifications` and `wishlist_listing_activity`, which are
    protected by the DB trigger from `5c8f1a2b3d4e_core_data_delete_guardrails`
    and must only be deleted via the explicit break-glass maintenance path in
    scripts/cleanup_operational_data.py, never from an in-process job.
    """
    done_cut = _cut_hours(settings.operational_retention_scrape_jobs_done_hours)
    failed_cut = _cut(settings.operational_retention_scrape_jobs_failed_days)
    return [
        (
            "system_logs",
            "DELETE FROM system_logs WHERE id IN (SELECT id FROM system_logs WHERE created_at < :cut LIMIT :batch)",
            {"cut": _cut(settings.operational_retention_system_logs_days), "batch": BATCH_SIZE},
        ),
        (
            "telemetry_events",
            "DELETE FROM telemetry_events WHERE id IN (SELECT id FROM telemetry_events WHERE created_at < :cut LIMIT :batch)",
            {"cut": _cut(settings.operational_retention_telemetry_events_days), "batch": BATCH_SIZE},
        ),
        (
            "scrape_jobs_done",
            "DELETE FROM scrape_jobs WHERE id IN (SELECT id FROM scrape_jobs WHERE created_at < :cut AND status = 'done' LIMIT :batch)",
            {"cut": done_cut, "batch": BATCH_SIZE},
        ),
        (
            "scrape_jobs_failed",
            "DELETE FROM scrape_jobs WHERE id IN (SELECT id FROM scrape_jobs WHERE created_at < :cut AND status = 'failed' LIMIT :batch)",
            {"cut": failed_cut, "batch": BATCH_SIZE},
        ),
        (
            "source_runs",
            "DELETE FROM source_runs WHERE id IN (SELECT id FROM source_runs WHERE created_at < :cut LIMIT :batch)",
            {"cut": _cut(settings.operational_retention_source_runs_days), "batch": BATCH_SIZE},
        ),
    ]


def run_operational_cleanup(db: Session) -> dict:
    """Delete expired rows from the non-protected operational tables.

    Isolates each rule in its own try/except so a failure on one table
    (e.g. an unexpected constraint) does not prevent the rest from running.
    """
    results: dict[str, int | str] = {}
    for name, sql, params in unprotected_cleanup_rules():
        try:
            results[name] = _delete_in_batches(db, sql, params)
        except Exception as e:
            db.rollback()
            results[name] = f"error: {e}"
    return results
