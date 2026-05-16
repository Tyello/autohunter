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
        payload={"skipped": False, "sent": 2, "previews": 3, "skipped_no_match": 1, "skipped_duplicate": 1, "skipped_daily_limit": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 1, "skipped_missing_lot_updated_at": 1, "errors": 0},
    )
    db.add(row)
    db.commit()
    out = build_auction_notification_status(db)
    assert out["last_status"] == "sent"
    assert out["last_sent"] == 2
    assert out["last_previews"] == 3


def test_status_reads_skipped_already_running(db):
    db.add(SystemLog(level="info", component="scheduler", message="auction_notification_scheduler_tick_skipped", payload={"skipped": True, "reason": "already_running"}))
    db.commit()
    out = build_auction_notification_status(db)
    assert out["last_status"] == "skipped"
    assert out["last_reason"] == "already_running"


def test_status_reads_skipped_bot_unavailable(db):
    db.add(SystemLog(level="warn", component="scheduler", message="auction_notification_scheduler_tick_skipped", payload={"skipped": True, "reason": "bot_unavailable_for_real_send"}))
    db.commit()
    out = build_auction_notification_status(db)
    assert out["last_status"] == "skipped"
    assert out["last_reason"] == "bot_unavailable_for_real_send"


def test_status_reads_failed_as_error(db):
    db.add(SystemLog(level="error", component="scheduler", message="auction_notification_scheduler_tick_failed", payload={"errors": 1, "reason": "error"}))
    db.commit()
    out = build_auction_notification_status(db)
    assert out["last_status"] == "error"
    assert out["last_errors"] == 1


def test_status_reads_finished_dry_run(db):
    db.add(SystemLog(level="info", component="scheduler", message="auction_notification_scheduler_tick_finished", payload={"skipped": False, "dry_run": True, "sent": 0, "previews": 4}))
    db.commit()
    out = build_auction_notification_status(db)
    assert out["last_status"] == "dry_run"
    assert out["last_previews"] == 4


def test_status_reads_new_skip_counters(db):
    db.add(SystemLog(level="info", component="scheduler", message="auction_notification_scheduler_tick_finished", payload={"skipped": False, "dry_run": True, "sent": 0, "previews": 1, "skipped_score_below_min": 2, "skipped_stale_lot": 3, "skipped_missing_lot_updated_at": 4}))
    db.commit()
    out = build_auction_notification_status(db)
    assert out["last_skipped_score_below_min"] == 2
    assert out["last_skipped_stale_lot"] == 3
