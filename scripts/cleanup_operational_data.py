from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db.session import SessionLocal
from app.core.settings import settings
from app.models.notification import Notification
from app.models.scrape_job import ScrapeJob
from app.models.source_run import SourceRun
from app.models.system_log import SystemLog
from app.models.telemetry_event import TelemetryEvent
from app.models.wishlist_listing_activity import WishlistListingActivity


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _delete_in_batches(db, model, where_clause, batch_size: int, apply: bool) -> int:
    total = 0
    while True:
        ids = [r[0] for r in db.query(model.id).filter(*where_clause).limit(batch_size).all()]
        if not ids:
            break
        total += len(ids)
        if apply:
            db.execute(delete(model).where(model.id.in_(ids)))
            db.commit()
    return total


def run_cleanup(*, apply: bool = False) -> dict[str, int]:
    if settings.database_url.startswith("sqlite") and apply:
        raise RuntimeError("Refusing destructive cleanup with SQLite database_url.")

    now = _utcnow()
    batch_size = int(getattr(settings, "operational_cleanup_batch_size", 500) or 500)
    out: dict[str, int] = {}

    with SessionLocal() as db:
        out["system_logs"] = _delete_in_batches(
            db,
            SystemLog,
            [SystemLog.created_at < now - timedelta(days=int(settings.retention_system_logs_days))],
            batch_size,
            apply,
        )
        out["telemetry_events"] = _delete_in_batches(
            db,
            TelemetryEvent,
            [TelemetryEvent.created_at < now - timedelta(days=int(settings.retention_telemetry_events_days))],
            batch_size,
            apply,
        )
        out["scrape_jobs"] = _delete_in_batches(
            db,
            ScrapeJob,
            [
                ScrapeJob.created_at < now - timedelta(days=int(settings.retention_scrape_jobs_days)),
                ScrapeJob.status.in_(["done", "failed"]),
            ],
            batch_size,
            apply,
        )
        out["source_runs"] = _delete_in_batches(
            db,
            SourceRun,
            [SourceRun.created_at < now - timedelta(days=int(settings.retention_source_runs_days))],
            batch_size,
            apply,
        )
        out["notifications"] = _delete_in_batches(
            db,
            Notification,
            [
                Notification.created_at < now - timedelta(days=int(settings.retention_notifications_days)),
                Notification.status.in_(["sent", "failed", "cancelled"]),
            ],
            batch_size,
            apply,
        )
        out["wishlist_listing_activity"] = _delete_in_batches(
            db,
            WishlistListingActivity,
            [WishlistListingActivity.created_at < now - timedelta(days=int(settings.retention_wishlist_activity_days))],
            batch_size,
            apply,
        )

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup operational tables with retention policies.")
    parser.add_argument("--apply", action="store_true", help="Apply deletes. Default is dry-run.")
    args = parser.parse_args()

    results = run_cleanup(apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[cleanup] mode={mode}")
    for key, value in results.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
