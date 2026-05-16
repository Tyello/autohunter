from datetime import datetime, timezone

from app.models.system_log import SystemLog
from app.services.auction_notification_status_service import build_auction_notification_status


def test_status_without_logs_returns_unknown(db):
    out = build_auction_notification_status(db)
    assert out["last_status"] == "unknown"
    assert out["last_run_at"] == "-"


def test_status_reads_latest_skipped_disabled(db):
    row = SystemLog(
        level="info",
        component="scheduler",
        message="auction_notification_scheduler_tick_skipped",
        payload={"skipped": True, "reason": "disabled", "sent": 0},
        created_at=datetime(2026, 5, 16, 17, 45, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 16, 17, 45, tzinfo=timezone.utc),
    )
    db.add(row)
    db.commit()
    out = build_auction_notification_status(db)
    assert out["last_status"] == "disabled"
    assert out["last_reason"] == "disabled"
    assert out["last_run_at"] == "2026-05-16 17:45 UTC"


def test_status_reads_finished_with_sent_and_previews(db):
    row = SystemLog(
        level="info",
        component="scheduler",
        message="auction_notification_scheduler_tick_finished",
        payload={"skipped": False, "sent": 2, "previews": 3, "skipped_no_match": 1, "skipped_duplicate": 1, "skipped_daily_limit": 0, "errors": 0},
    )
    db.add(row)
    db.commit()
    out = build_auction_notification_status(db)
    assert out["last_status"] == "sent"
    assert out["last_sent"] == 2
    assert out["last_previews"] == 3
