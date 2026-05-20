from datetime import datetime, timezone
import uuid

from app.models.app_kv import AppKV
from app.models.auction_lot import AuctionLot
from app.models.source_config import SourceConfig
from app.models.system_log import SystemLog
from app.models.wishlist import Wishlist
from app.models.user import User
from app.services import auction_notification_readiness_service as readiness_service
from app.services.app_kv_service import set_kv
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
    db.add(AuctionLot(source="vip_auctions", external_id="1", item_type="car", year=2020, url="https://x", current_bid=10, updated_at=datetime.now(timezone.utc)))
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


def test_readiness_uses_runtime_min_score_and_age(db):
    _seed_source(db, eligible=True)
    set_kv(db, "auction_notification_settings", {"min_score": 40, "max_lot_age_hours": 96, "max_per_user_per_day": 5})
    out = build_auction_notification_readiness(db)
    quality = next(c for c in out["checks"] if c["key"] == "quality_gates")
    assert quality["status"] == "warn"
    assert "min_score < 50" in quality["detail"]


def test_readiness_shows_kill_switch(db, monkeypatch):
    _seed_source(db, eligible=True)
    monkeypatch.setattr("app.services.auction_notification_settings_service.settings.auction_notifications_kill_switch", True)
    out = build_auction_notification_readiness(db)
    ks = next(c for c in out["checks"] if c["key"] == "kill_switch")
    assert ks["status"] == "warn"


def test_readiness_real_estate_source_does_not_count_as_car_pilot_ready(db):
    db.add(SourceConfig(source="win_auctions", source_type="auction", is_enabled=True, user_eligible=False))
    db.add(AuctionLot(source="win_auctions", external_id="win-re", item_type="real_estate", url="https://win/re", current_bid=100000, updated_at=datetime.now(timezone.utc)))
    db.commit()

    out = build_auction_notification_readiness(db)

    win_summary = out["summary"]["source_car_pilot"]["win_auctions"]
    assert win_summary["car_lots"] == 0
    assert win_summary["source_ready_for_user_car_pilot"] is False
    assert any(c["key"] == "source_functional_without_car_lots" and "win_auctions" in c["detail"] for c in out["checks"])


def test_readiness_car_without_bid_generates_experimental_warning(db):
    db.add(SourceConfig(source="mega_auctions", source_type="auction", is_enabled=True, user_eligible=False))
    db.add(AuctionLot(source="mega_auctions", external_id="mega-car", item_type="car", url="https://mega/car", year=2020, updated_at=datetime.now(timezone.utc)))
    db.commit()

    out = build_auction_notification_readiness(db)

    mega_summary = out["summary"]["source_car_pilot"]["mega_auctions"]
    assert mega_summary["car_lots"] == 1
    assert mega_summary["source_ready_for_user_car_pilot"] is False
    assert any(c["key"] == "source_car_lots_not_ready" and "mega_auctions" in c["detail"] and "sem lance" in c["detail"] for c in out["checks"])


def test_readiness_vip_car_with_bid_counts_as_car_pilot_ready(db):
    _seed_source(db, eligible=True)
    db.add(AuctionLot(source="vip_auctions", external_id="vip-car", item_type="car", url="https://vip/car", year=2021, current_bid=50000, updated_at=datetime.now(timezone.utc)))
    db.commit()

    out = build_auction_notification_readiness(db)

    vip_summary = out["summary"]["source_car_pilot"]["vip_auctions"]
    assert vip_summary["source_ready_for_user_car_pilot"] is True
    assert "vip_auctions" in out["summary"]["car_pilot_ready_sources"]


def test_readiness_win_not_user_facing_even_with_recent_car(db):
    db.add(SourceConfig(source="win_auctions", source_type="auction", is_enabled=True, user_eligible=False, status="experimental_functional_vehicle", extra={"allowed_item_types":["car"]}))
    db.add(AuctionLot(source="win_auctions", external_id="win-car", item_type="car", year=2022, initial_bid=10000, url="https://win/car", updated_at=datetime.now(timezone.utc)))
    db.commit()
    out = build_auction_notification_readiness(db)
    win_summary = out["summary"]["source_car_pilot"]["win_auctions"]
    assert win_summary["data_quality_ready_car"] is True
    assert win_summary["source_ready_for_user_car_pilot"] is False
    assert "win_auctions" not in out["summary"]["car_pilot_ready_sources"]
