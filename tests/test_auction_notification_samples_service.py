from app.services.app_kv_service import set_kv
from app.services.auction_notification_samples_service import build_auction_notification_samples


def test_samples_empty_when_missing(db):
    out = build_auction_notification_samples(db)
    assert out == {"created_at": "-", "summary": {}, "samples": []}


def test_samples_returns_limited_data(db):
    set_kv(
        db,
        "auction_last_dry_run_samples",
        {
            "created_at": "2026-05-16T21:10:00+00:00",
            "summary": {"previews": 12, "skipped_score_below_min": 1, "skipped_stale_lot": 2, "skipped_missing_lot_updated_at": 3},
            "samples": [{"title": f"x{i}"} for i in range(12)],
        },
    )
    out = build_auction_notification_samples(db, limit=10)
    assert out["summary"]["previews"] == 12
    assert len(out["samples"]) == 10
