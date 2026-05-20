from datetime import datetime, timedelta, timezone

from app.services.auction_lot_service import upsert_lot
from app.services.auction_quality_service import build_auction_quality_report


def _seed(db, source: str, external_id: str, **data):
    payload = {"source": source, "external_id": external_id}
    payload.update(data)
    upsert_lot(db, payload)


def test_quality_source_without_lots_returns_sem_dados(db):
    report = build_auction_quality_report(db, source="vip")
    src = report["sources"][0]
    assert src["source"] == "vip_auctions"
    assert src["total_lots"] == 0
    assert src["quality_score"] == 0
    assert src["quality_label"] == "sem dados"


def test_quality_full_coverage_scores_boa(db):
    _seed(
        db,
        "vip_auctions",
        "v1",
        title="Carro",
        year=2020,
        current_bid=100,
        initial_bid=90,
        auction_end_at=datetime.now(timezone.utc) + timedelta(days=1),
        city="SP",
        state="SP",
        url="https://x",
        image_count=1,
        status="open",
    )
    db.commit()
    src = build_auction_quality_report(db, source="vip")["sources"][0]
    assert src["quality_score"] >= 80
    assert src["quality_label"] == "boa"


def test_quality_coverages_and_updated_last_24h_and_source_filter(db):
    now = datetime.now(timezone.utc)
    _seed(db, "vip_auctions", "v1", title="A", year=2020, current_bid=10, url="https://1", status="live", city="S", state="SP", image_count=1)
    _seed(db, "vip_auctions", "v2", title="B", initial_bid=20, auction_end_at=now + timedelta(hours=2), url="https://2", status="ended")
    _seed(db, "mega_auctions", "m1", title="M", url="https://m")
    db.commit()

    # force old updated_at for one row
    from app.models.auction_lot import AuctionLot

    lot = db.query(AuctionLot).filter(AuctionLot.source == "vip_auctions", AuctionLot.external_id == "v2").first()
    lot.updated_at = now - timedelta(days=2)
    db.commit()

    src = build_auction_quality_report(db, source="vip")["sources"][0]
    assert src["total_lots"] == 2
    assert src["with_current_bid_count"] == 1
    assert src["with_initial_bid_count"] == 1
    assert src["with_year_count"] == 1
    assert src["with_auction_end_at_count"] == 1
    assert src["with_city_state_count"] == 1
    assert src["with_url_count"] == 2
    assert src["with_image_count"] == 1
    assert src["updated_last_24h"] == 1
    assert src["open_or_live_count"] == 1
    assert src["ended_count"] >= 1


def test_quality_report_includes_registry_sources_without_lots(db):
    report = build_auction_quality_report(db)
    keys = {x["source"] for x in report["sources"]}
    assert "copart_auctions" in keys
    assert "vip_auctions" in keys


def test_quality_car_pilot_readiness_uses_runtime_max_lot_age_window(db):
    from app.models.auction_lot import AuctionLot
    from app.services.app_kv_service import set_kv

    now = datetime.now(timezone.utc)
    _seed(
        db,
        "vip_auctions",
        "vip-30h",
        title="Civic",
        item_type="car",
        year=2020,
        current_bid=50000,
        url="https://vip/30h",
        status="open",
    )
    lot = db.query(AuctionLot).filter(AuctionLot.source == "vip_auctions", AuctionLot.external_id == "vip-30h").one()
    lot.updated_at = now - timedelta(hours=30)
    set_kv(db, "auction_notification_settings", {"max_lot_age_hours": 48})
    db.commit()

    src = build_auction_quality_report(db, source="vip")["sources"][0]

    assert src["updated_last_24h"] == 0
    assert src["car_pilot_window_hours"] == 48
    assert src["source_ready_for_user_car_pilot"] is True


def test_quality_user_facing_requires_source_gates(db):
    _seed(db, "win_auctions", "w1", title="Civic", item_type="car", year=2020, initial_bid=1000, url="https://win/1")
    db.commit()
    src = build_auction_quality_report(db, source="win")["sources"][0]
    assert src["data_quality_ready_car"] is True
    assert src["user_facing_ready_car"] is False
    assert "user_eligible=false" in src["user_facing_ready_reason"]


def test_quality_user_facing_ready_when_production_and_eligible(db):
    from app.models.source_config import SourceConfig
    db.add(SourceConfig(source="vip_auctions", source_type="auction", is_enabled=True, user_eligible=True, status="production_ready", extra={"allowed_item_types":["car"]}))
    _seed(
        db,
        "vip_auctions",
        "v-ready",
        title="Civic",
        item_type="car",
        year=2020,
        initial_bid=1000,
        url="https://vip/1",
        status="open",
        auction_end_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.commit()
    src = build_auction_quality_report(db, source="vip")["sources"][0]
    assert src["data_quality_ready_car"] is True
    assert src["user_facing_ready_car"] is True


def test_quality_warns_when_unknown_status_and_missing_end(db):
    from app.models.source_config import SourceConfig
    db.add(SourceConfig(source="win_auctions", source_type="auction", is_enabled=True, user_eligible=False, status="experimental_vehicle_route_found"))
    _seed(db, "win_auctions", "w2", title="Civic", item_type="car", year=2020, initial_bid=1000, url="https://win/2", status="unknown")
    db.commit()
    src = build_auction_quality_report(db, source="win")["sources"][0]
    assert "sem status/encerramento; manter experimental" in (src.get("critical_warnings") or [])
    assert src["data_quality_ready_car"] is True
