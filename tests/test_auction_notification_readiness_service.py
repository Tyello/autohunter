from datetime import datetime, timezone
import uuid

from app.models.app_kv import AppKV
from app.models.auction_lot import AuctionLot
from app.models.source_config import SourceConfig
from app.models.system_log import SystemLog
from app.models.wishlist import Wishlist
from app.models.user import User
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
