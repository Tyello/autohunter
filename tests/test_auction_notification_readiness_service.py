from datetime import datetime, timezone
import uuid

from app.models.app_kv import AppKV
from app.models.auction_lot import AuctionLot
from app.models.source_config import SourceConfig
from app.models.system_log import SystemLog
from app.models.wishlist import Wishlist
from app.models.user import User
from app.services import auction_notification_readiness_service as readiness_service
from app.services.auction_notification_readiness_service import build_auction_notification_readiness


def _seed_source(db, *, eligible=True):
    db.add(SourceConfig(source="vip_auctions", source_type="auction", is_enabled=True, user_eligible=eligible))
    db.commit()


def test_readiness_fail_without_eligible_source(db):
    out = build_auction_notification_readiness(db)
    assert out["status"] == "fail"


def test_readiness_warn_without_opt_in_wishlist(db):
    _seed_source(db, eligible=True)
    out = build_auction_notification_readiness(db)
    assert out["status"] in {"warn", "fail"}
    assert any(c["key"] == "wishlists_opt_in" and c["status"] == "warn" for c in out["checks"])


def test_readiness_recent_lot_and_sample_ok(db):
    _seed_source(db, eligible=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=777001, username="u")
    db.add(user)
    db.flush()
    db.add(Wishlist(user_id=user.id, query="uno", is_active=True, include_auctions=True))
    db.add(AuctionLot(source="vip_auctions", external_id="1", url="https://x", current_bid=10, updated_at=datetime.now(timezone.utc)))
    db.add(SystemLog(level="info", component="scheduler", message="auction_notification_scheduler_tick_finished", payload={}))
    db.add(AppKV(key="auction_last_dry_run_samples", value={"samples": [{"x": 1}]}))
    db.commit()
    out = build_auction_notification_readiness(db)
    assert out["summary"]["recent_eligible_lots_with_bid"] >= 1
    assert any(c["key"] == "dry_run_samples" and c["status"] == "ok" for c in out["checks"])


def test_readiness_scheduler_failed_is_fail(db):
    _seed_source(db, eligible=True)
    db.add(SystemLog(level="error", component="scheduler", message="auction_notification_scheduler_tick_failed", payload={}))
    db.commit()
    out = build_auction_notification_readiness(db)
    assert out["status"] == "fail"


def test_readiness_scheduler_missing_warn(db):
    _seed_source(db, eligible=True)
    out = build_auction_notification_readiness(db)
    assert any(c["key"] == "scheduler_last_execution" and c["status"] == "warn" for c in out["checks"])


def test_readiness_real_send_enabled_is_fail(db, monkeypatch):
    _seed_source(db, eligible=True)
    monkeypatch.setattr(readiness_service.settings, "auction_notifications_enabled", True)
    monkeypatch.setattr(readiness_service.settings, "auction_notifications_dry_run", False)

    out = build_auction_notification_readiness(db)

    assert out["status"] == "fail"
    safe = next(c for c in out["checks"] if c["key"] == "safe_config")
    assert safe["status"] == "fail"


def test_readiness_quality_gate_warnings(db, monkeypatch):
    _seed_source(db, eligible=True)
    monkeypatch.setattr(readiness_service.settings, "auction_notifications_min_score", 40)
    monkeypatch.setattr(readiness_service.settings, "auction_notifications_max_lot_age_hours", 96)
    monkeypatch.setattr(readiness_service.settings, "auction_notifications_max_per_user_per_day", 5)

    out = build_auction_notification_readiness(db)

    quality = next(c for c in out["checks"] if c["key"] == "quality_gates")
    assert quality["status"] == "warn"
    assert "min_score < 50" in quality["detail"]
    assert "max_lot_age_hours fora de (0,72]" in quality["detail"]
    assert "max_per_user_per_day > 3" in quality["detail"]


def test_readiness_samples_missing_warn(db):
    _seed_source(db, eligible=True)

    out = build_auction_notification_readiness(db)

    samples = next(c for c in out["checks"] if c["key"] == "dry_run_samples")
    assert samples["status"] == "warn"


def test_readiness_samples_present_ok(db):
    _seed_source(db, eligible=True)
    db.add(AppKV(key="auction_last_dry_run_samples", value={"samples": [{"id": 1}]}))
    db.commit()

    out = build_auction_notification_readiness(db)

    samples = next(c for c in out["checks"] if c["key"] == "dry_run_samples")
    assert samples["status"] == "ok"


def test_readiness_allowed_categories_safe_ok(db):
    _seed_source(db, eligible=True)
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "vip_auctions").first()
    cfg.extra = {"allowed_item_types": ["car"]}
    db.add(cfg); db.commit()
    out = build_auction_notification_readiness(db)
    check = next(c for c in out["checks"] if c["key"] == "auction_allowed_categories_safe")
    assert check["status"] == "ok"


def test_readiness_allowed_categories_safe_warn(db):
    _seed_source(db, eligible=True)
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "vip_auctions").first()
    cfg.extra = {"allowed_item_types": ["car", "motorcycle"]}
    db.add(cfg); db.commit()
    out = build_auction_notification_readiness(db)
    check = next(c for c in out["checks"] if c["key"] == "auction_allowed_categories_safe")
    assert check["status"] == "warn"
