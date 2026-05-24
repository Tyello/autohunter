from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.settings import settings
from app.db.session import SessionLocal

BATCH_SIZE = 1000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cut(days: int) -> datetime:
    return _utcnow() - timedelta(days=max(1, int(days)))


def _cut_hours(hours: int) -> datetime:
    return _utcnow() - timedelta(hours=max(1, int(hours)))


def _count_candidates(db, sql: str, params: dict) -> int:
    return int(db.execute(text(sql), params).scalar_one())


def _delete_candidates_in_batches(db, sql: str, params: dict) -> int:
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


def _log_warning(db, message: str, payload: dict) -> None:
    db.execute(
        text(
            """
            INSERT INTO system_logs (level, component, message, payload, created_at)
            VALUES ('warn', 'cleanup_operational_data', :message, CAST(:payload AS JSONB), NOW())
            """
        ),
        {"message": message, "payload": __import__('json').dumps(payload)},
    )
    db.commit()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    apply = bool(args.apply)

    if settings.database_url.startswith('sqlite') and apply:
        raise SystemExit('Refusing destructive cleanup on SQLite. Use dry-run only.')

    done_cut = _cut_hours(settings.operational_retention_scrape_jobs_done_hours)
    failed_cut = _cut(settings.operational_retention_scrape_jobs_failed_days)
    queued_old_cut = _cut_hours(2)

    rules = [
        (
            'system_logs',
            'SELECT count(*) FROM system_logs WHERE created_at < :cut',
            'DELETE FROM system_logs WHERE id IN (SELECT id FROM system_logs WHERE created_at < :cut LIMIT :batch)',
            {'cut': _cut(settings.operational_retention_system_logs_days), 'batch': BATCH_SIZE},
        ),
        (
            'telemetry_events',
            'SELECT count(*) FROM telemetry_events WHERE created_at < :cut',
            'DELETE FROM telemetry_events WHERE id IN (SELECT id FROM telemetry_events WHERE created_at < :cut LIMIT :batch)',
            {'cut': _cut(settings.operational_retention_telemetry_events_days), 'batch': BATCH_SIZE},
        ),
        (
            'scrape_jobs_done',
            "SELECT count(*) FROM scrape_jobs WHERE created_at < :cut AND status = 'done'",
            "DELETE FROM scrape_jobs WHERE id IN (SELECT id FROM scrape_jobs WHERE created_at < :cut AND status = 'done' LIMIT :batch)",
            {'cut': done_cut, 'batch': BATCH_SIZE},
        ),
        (
            'scrape_jobs_failed',
            "SELECT count(*) FROM scrape_jobs WHERE created_at < :cut AND status = 'failed'",
            "DELETE FROM scrape_jobs WHERE id IN (SELECT id FROM scrape_jobs WHERE created_at < :cut AND status = 'failed' LIMIT :batch)",
            {'cut': failed_cut, 'batch': BATCH_SIZE},
        ),
        (
            'source_runs',
            'SELECT count(*) FROM source_runs WHERE created_at < :cut',
            'DELETE FROM source_runs WHERE id IN (SELECT id FROM source_runs WHERE created_at < :cut LIMIT :batch)',
            {'cut': _cut(settings.operational_retention_source_runs_days), 'batch': BATCH_SIZE},
        ),
        (
            'notifications',
            "SELECT count(*) FROM notifications WHERE created_at < :cut AND status IN ('sent','failed','suppressed','discarded')",
            "DELETE FROM notifications WHERE id IN (SELECT id FROM notifications WHERE created_at < :cut AND status IN ('sent','failed','suppressed','discarded') LIMIT :batch)",
            {'cut': _cut(settings.operational_retention_notifications_days), 'batch': BATCH_SIZE},
        ),
        (
            'wishlist_listing_activity',
            'SELECT count(*) FROM wishlist_listing_activity WHERE created_at < :cut',
            'DELETE FROM wishlist_listing_activity WHERE id IN (SELECT id FROM wishlist_listing_activity WHERE created_at < :cut LIMIT :batch)',
            {'cut': _cut(settings.operational_retention_wishlist_activity_days), 'batch': BATCH_SIZE},
        ),
    ]

    with SessionLocal() as db:
        queued_old = _count_candidates(
            db,
            "SELECT count(*) FROM scrape_jobs WHERE status = 'queued' AND created_at < :cut",
            {'cut': queued_old_cut},
        )
        if queued_old > 0 and 'sqlite' not in settings.database_url:
            try:
                _log_warning(db, 'queued scrape_jobs older than 2h detected', {'queued_old_count': queued_old})
            except Exception:
                db.rollback()

        mode = 'apply' if apply else 'dry-run'
        print(f'[{mode}] scrape_jobs_queued_old_2h: {queued_old}')

        for name, count_sql, delete_sql, params in rules:
            count = _count_candidates(db, count_sql, params) if not apply else _delete_candidates_in_batches(db, delete_sql, params)
            print(f'[{mode}] {name}: {count}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
