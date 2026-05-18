from app.models.app_kv import AppKV
from app.models.system_log import SystemLog
from app.services import auction_dry_run_digest_service as digest_service
from app.services.auction_dry_run_digest_service import build_auction_dry_run_digest


def test_digest_no_logs_no_appkv_returns_no_data(db):
    out = build_auction_dry_run_digest(db, hours=24)
    assert out["runs"] == 0
    assert out["recommendation"]["status"] == "no_data"


def test_digest_uses_appkv_summary_fallback(db):
    db.add(AppKV(key="auction_last_dry_run_samples", value={"summary": {"wishlists_scanned": 6, "wishlists_with_matches": 2, "previews": 2, "errors": 0, "skipped_no_match": 8}}))
    db.commit()
    out = build_auction_dry_run_digest(db)
    assert out["wishlists_scanned"] == 6
    assert out["previews"] == 2


def test_digest_returns_latest_samples_and_rejections(db):
    db.add(AppKV(key="auction_last_dry_run_samples", value={"samples": [{"title": "A"}], "rejections": [{"title": "B", "reason": "stale_lot"}]}))
    db.commit()
    out = build_auction_dry_run_digest(db)
    assert out["latest_samples"][0]["title"] == "A"
    assert out["latest_rejections"][0]["title"] == "B"


def test_digest_errors_recommendation_needs_attention(db):
    digest_service.get_auction_notification_runtime_settings = lambda _db: {"enabled": True, "dry_run": True}
    db.add(SystemLog(component="scheduler", message="auction_notification_scheduler_tick_failed", payload={"errors": 2}))
    db.commit()
    out = build_auction_dry_run_digest(db)
    assert out["errors"] == 2
    assert out["recommendation"]["status"] == "needs_attention"


def test_digest_previews_healthy_keep_dry_run(db):
    digest_service.get_auction_notification_runtime_settings = lambda _db: {"enabled": True, "dry_run": True}
    db.add(SystemLog(component="scheduler", message="auction_notification_scheduler_tick_finished", payload={"dry_run": True, "previews": 2, "errors": 0}))
    db.commit()
    out = build_auction_dry_run_digest(db)
    assert out["previews"] == 2
    assert out["recommendation"]["status"] == "keep_dry_run"


def test_digest_never_recommends_automatic_real_send(db):
    digest_service.get_auction_notification_runtime_settings = lambda _db: {"enabled": True, "dry_run": False}
    out = build_auction_dry_run_digest(db)
    assert out["recommendation"]["status"] == "needs_attention"
    assert "Envio real aparentemente ativo" in out["recommendation"]["message"]
    assert "ativar envio real" not in out["recommendation"]["message"].lower()
    assert "envio automático real" not in out["recommendation"]["message"].lower()


def test_digest_merges_summary_with_partial_scheduler_log(db):
    digest_service.get_auction_notification_runtime_settings = lambda _db: {"enabled": True, "dry_run": True}
    db.add(SystemLog(component="scheduler", message="auction_notification_scheduler_tick_finished", payload={"dry_run": True, "previews": 1, "skipped_no_match": 1, "errors": 0}))
    db.add(AppKV(key="auction_last_dry_run_samples", value={"summary": {"wishlists_scanned": 2, "wishlists_with_matches": 1, "previews": 1, "skipped_stale_lot": 1, "skipped_score_below_min": 0}}))
    db.commit()
    out = build_auction_dry_run_digest(db)
    assert out["runs"] == 1
    assert out["wishlists_scanned"] == 2
    assert out["wishlists_with_matches"] == 1
    assert out["previews"] == 1
    assert out["skips"]["stale_lot"] == 1
    assert out["skips"]["no_match"] == 1
    assert out["recommendation"]["status"] == "keep_dry_run"
    assert out["history_note"]
