from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.settings import settings
from app.db.session import SessionLocal
from app.services.operational_data_cleanup_service import (
    BATCH_SIZE,
    unprotected_cleanup_rules,
)

# Tables guarded by the core-data-delete trigger (5c8f1a2b3d4e_core_data_delete_guardrails).
# A physical DELETE against them requires SET LOCAL app.allow_core_data_delete='on'
# inside the same transaction, set explicitly below — never from the in-process
# APScheduler job (see app/services/notifications_cleanup_service.py).
_PROTECTED_TABLES = ("notifications", "wishlist_listing_activity")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cut(days: int) -> datetime:
    return _utcnow() - timedelta(days=max(1, int(days)))


def _cut_hours(hours: int) -> datetime:
    return _utcnow() - timedelta(hours=max(1, int(hours)))


def _count_candidates(db, sql: str, params: dict) -> int:
    return int(db.execute(text(sql), params).scalar_one())


def _delete_candidates_in_batches(db, sql: str, params: dict, *, protected: bool = False) -> int:
    total = 0
    while True:
        if protected and not settings.database_url.startswith("sqlite"):
            db.execute(text("SET LOCAL app.allow_core_data_delete = 'on'"))
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
        {"message": message, "payload": json.dumps(payload)},
    )
    db.commit()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    apply = bool(args.apply)

    if settings.database_url.startswith('sqlite') and apply:
        raise SystemExit('Refusing destructive cleanup on SQLite. Use dry-run only.')

    queued_old_cut = _cut_hours(2)

    # count_sql mirrors the delete_sql WHERE clause from operational_data_cleanup_service,
    # kept local only for dry-run reporting (no writes).
    _count_sql_by_table = {
        'system_logs': 'SELECT count(*) FROM system_logs WHERE created_at < :cut',
        'telemetry_events': 'SELECT count(*) FROM telemetry_events WHERE created_at < :cut',
        'scrape_jobs_done': "SELECT count(*) FROM scrape_jobs WHERE created_at < :cut AND status = 'done'",
        'scrape_jobs_failed': "SELECT count(*) FROM scrape_jobs WHERE created_at < :cut AND status = 'failed'",
        'source_runs': 'SELECT count(*) FROM source_runs WHERE created_at < :cut',
    }
    rules = [
        (name, _count_sql_by_table[name], delete_sql, params, False)
        for name, delete_sql, params in unprotected_cleanup_rules()
    ]
    rules += [
        (
            'notifications',
            "SELECT count(*) FROM notifications WHERE created_at < :cut AND status IN ('sent','failed','suppressed','discarded')",
            "DELETE FROM notifications WHERE id IN (SELECT id FROM notifications WHERE created_at < :cut AND status IN ('sent','failed','suppressed','discarded') LIMIT :batch)",
            {'cut': _cut(settings.operational_retention_notifications_days), 'batch': BATCH_SIZE},
            True,
        ),
        (
            'wishlist_listing_activity',
            'SELECT count(*) FROM wishlist_listing_activity WHERE created_at < :cut',
            'DELETE FROM wishlist_listing_activity WHERE id IN (SELECT id FROM wishlist_listing_activity WHERE created_at < :cut LIMIT :batch)',
            {'cut': _cut(settings.operational_retention_wishlist_activity_days), 'batch': BATCH_SIZE},
            True,
        ),
    ]
    assert all(name in _PROTECTED_TABLES for name, _, _, _, protected in rules if protected)

    with SessionLocal() as db:
        queued_old = _count_candidates(
            db,
            "SELECT count(*) FROM scrape_jobs WHERE status = 'queued' AND created_at < :cut",
            {'cut': queued_old_cut},
        )
        if apply and queued_old > 0 and 'sqlite' not in settings.database_url:
            try:
                _log_warning(db, 'queued scrape_jobs older than 2h detected', {'queued_old_count': queued_old})
            except Exception:
                db.rollback()

        mode = 'apply' if apply else 'dry-run'
        print(f'[{mode}] scrape_jobs_queued_old_2h: {queued_old}')

        for name, count_sql, delete_sql, params, protected in rules:
            try:
                if apply:
                    result = _delete_candidates_in_batches(db, delete_sql, params, protected=protected)
                else:
                    result = _count_candidates(db, count_sql, params)
                print(f'[{mode}] {name}: {result}')
            except Exception as e:
                db.rollback()
                print(f'[{mode}] {name}: error: {e}')
                try:
                    _log_warning(db, f'cleanup rule failed: {name}', {'error': str(e)})
                except Exception:
                    db.rollback()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
