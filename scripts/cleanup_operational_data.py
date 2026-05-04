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


def _delete_in_batches(db, sql: str, params: dict, *, apply: bool) -> int:
    total = 0
    while True:
        rows = db.execute(text(sql), params).fetchall()
        n = len(rows)
        total += n
        if not apply or n == 0:
            break
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
        ("system_logs", "DELETE FROM system_logs WHERE id IN (SELECT id FROM system_logs WHERE created_at < :cut LIMIT :batch) RETURNING id", {"cut": _cut(settings.operational_retention_system_logs_days), "batch": BATCH_SIZE}),
        ("telemetry_events", "DELETE FROM telemetry_events WHERE id IN (SELECT id FROM telemetry_events WHERE created_at < :cut LIMIT :batch) RETURNING id", {"cut": _cut(settings.operational_retention_telemetry_events_days), "batch": BATCH_SIZE}),
        ("scrape_jobs", "DELETE FROM scrape_jobs WHERE id IN (SELECT id FROM scrape_jobs WHERE created_at < :cut AND status IN ('done','failed') LIMIT :batch) RETURNING id", {"cut": _cut(settings.operational_retention_scrape_jobs_days), "batch": BATCH_SIZE}),
        ("source_runs", "DELETE FROM source_runs WHERE id IN (SELECT id FROM source_runs WHERE created_at < :cut LIMIT :batch) RETURNING id", {"cut": _cut(settings.operational_retention_source_runs_days), "batch": BATCH_SIZE}),
        ("notifications", "DELETE FROM notifications WHERE id IN (SELECT id FROM notifications WHERE created_at < :cut AND status IN ('sent','failed','cancelled') LIMIT :batch) RETURNING id", {"cut": _cut(settings.operational_retention_notifications_days), "batch": BATCH_SIZE}),
        ("wishlist_listing_activity", "DELETE FROM wishlist_listing_activity WHERE id IN (SELECT id FROM wishlist_listing_activity WHERE created_at < :cut LIMIT :batch) RETURNING id", {"cut": _cut(settings.operational_retention_wishlist_activity_days), "batch": BATCH_SIZE}),
    ]

    with SessionLocal() as db:
        for name, sql, params in rules:
            count = _delete_in_batches(db, sql, params, apply=apply)
            mode = 'apply' if apply else 'dry-run'
            print(f'[{mode}] {name}: {count}')
        if not apply:
            db.rollback()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
