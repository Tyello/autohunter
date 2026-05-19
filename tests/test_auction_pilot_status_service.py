from datetime import datetime, timezone
import uuid

from app.models.app_kv import AppKV
from app.models.auction_lot import AuctionLot
from app.models.source_config import SourceConfig
from app.models.system_log import SystemLog
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.app_kv_service import set_kv
from app.services.auction_pilot_status_service import build_auction_pilot_status


def _seed_vip(db, eligible=True):
    db.add(SourceConfig(source="vip_auctions", source_type="auction", is_enabled=True, user_eligible=eligible, extra={"allowed_item_types": ["car"]}))


def test_pilot_warn_without_auction_wishlists(db):
    _seed_vip(db)
    db.commit()
    out = build_auction_pilot_status(db)
    assert out["wishlists"]["include_auctions_total"] == 0
    assert out["health"]["status"] == "warning"


def test_pilot_ok_with_vip_car_ready(db):
    _seed_vip(db)
    db.add(AuctionLot(source="vip_auctions", external_id="1", item_type="car", year=2020, url="https://x", current_bid=1, updated_at=datetime.now(timezone.utc)))
    u = User(id=uuid.uuid4(), telegram_chat_id=123)
    db.add(u); db.flush()
    db.add(Wishlist(user_id=u.id, query="uno", is_active=True, include_auctions=True))
    db.commit()
    out = build_auction_pilot_status(db)
    assert out["sources"]["user_eligible"] == ["vip_auctions"]
    assert "vip_auctions" in out["sources"]["ready_car_pilot"]


def test_pilot_warns_unsafe_user_eligible_source(db):
    _seed_vip(db)
    db.add(SourceConfig(source="mega_auctions", source_type="auction", is_enabled=True, user_eligible=True, extra={"allowed_item_types": ["car"]}))
    db.commit()
    out = build_auction_pilot_status(db)
    assert "mega_auctions" in out["sources"]["unsafe_user_eligible"]
    assert out["health"]["status"] == "warning"


def test_pilot_mode_dry_run_true_disables_automatic_real(db):
    _seed_vip(db)
    set_kv(db, "auction_notification_settings", {"enabled": True, "dry_run": True})
    out = build_auction_pilot_status(db)
    assert out["mode"]["automatic_real_active"] is False


def test_pilot_mode_dry_run_false_blocks(db):
    _seed_vip(db)
    set_kv(db, "auction_notification_settings", {"enabled": True, "dry_run": False})
    out = build_auction_pilot_status(db)
    assert out["mode"]["automatic_real_active"] is True
    assert out["health"]["status"] == "blocked"


def test_pilot_aggregates_manual_real_24h(db):
    _seed_vip(db)
    db.add(SystemLog(level="info", component="bot.admin", message="auction_notification_manual_real_run_finished", payload={"sent": 2, "skipped_duplicate": 1, "errors": 0}))
    db.add(SystemLog(level="error", component="bot.admin", message="auction_notification_manual_real_run_failed", payload={"sent": 1, "skipped_duplicate": 2, "errors": 3}))
    db.add(AppKV(key="auction_last_dry_run_samples", value={"created_at": "2026-05-19 17:30 UTC", "summary": {"previews": 2}}))
    db.commit()
    out = build_auction_pilot_status(db)
    assert out["notifications"]["manual_real_sent_24h"] == 3
    assert out["notifications"]["duplicates_24h"] == 3
    assert out["notifications"]["errors_24h"] == 3



def test_pilot_manual_real_reads_bot_admin_logs_regression(db):
    _seed_vip(db)
    db.add(SystemLog(level="info", component="bot.admin", message="auction_notification_manual_real_run_finished", payload={"sent": 1, "skipped_duplicate": 1, "errors": 0}))
    db.commit()
    out = build_auction_pilot_status(db)
    assert out["notifications"]["last_manual_real_sent"] == 1
    assert out["notifications"]["duplicates_24h"] == 1

def test_pilot_manual_real_message_only_filter_accepts_scheduler_component_too(db):
    _seed_vip(db)
    db.add(SystemLog(level="info", component="scheduler", message="auction_notification_manual_real_run_finished", payload={"sent": 2, "skipped_duplicate": 0, "errors": 0}))
    db.commit()
    out = build_auction_pilot_status(db)
    assert out["notifications"]["last_manual_real_sent"] == 2
