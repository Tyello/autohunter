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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    apply = bool(args.apply)

    if settings.database_url.startswith('sqlite') and apply:
        raise SystemExit('Refusing destructive cleanup on SQLite. Use dry-run only.')

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
            'scrape_jobs',
            "SELECT count(*) FROM scrape_jobs WHERE created_at < :cut AND status IN ('done','failed')",
            "DELETE FROM scrape_jobs WHERE id IN (SELECT id FROM scrape_jobs WHERE created_at < :cut AND status IN ('done','failed') LIMIT :batch)",
            {'cut': _cut(settings.operational_retention_scrape_jobs_days), 'batch': BATCH_SIZE},
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
        for name, count_sql, delete_sql, params in rules:
            count = _count_candidates(db, count_sql, params) if not apply else _delete_candidates_in_batches(db, delete_sql, params)
            mode = 'apply' if apply else 'dry-run'
            print(f'[{mode}] {name}: {count}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
