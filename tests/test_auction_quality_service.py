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
