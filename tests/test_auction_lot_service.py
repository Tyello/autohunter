from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.auction_lot_service import (
    get_auction_stats,
    list_lots_by_source,
    list_motorcycle_lots,
    list_upcoming_lots,
    upsert_event,
    upsert_lot,
)


def test_upsert_event_create_and_update(db):
    event = upsert_event(db, {"source": "copart_auctions", "external_id": "ev-1", "title": "Evento 1", "status": "scheduled"})
    db.commit()
    assert event.id is not None

    updated = upsert_event(db, {"source": "copart_auctions", "external_id": "ev-1", "title": "Evento 1 atualizado", "status": "live"})
    db.commit()
    assert updated.id == event.id
    assert updated.title == "Evento 1 atualizado"
    assert updated.status == "live"


def test_upsert_lot_create_update_and_seen_timestamps(db):
    lot, created = upsert_lot(db, {"source": "copart_auctions", "external_id": "lot-1", "title": "Lote 1", "status": "scheduled", "total_bids": 1})
    db.commit()
    assert created is True
    first_seen = lot.first_seen_at
    first_last_seen = lot.last_seen_at

    lot2, created2 = upsert_lot(db, {"source": "copart_auctions", "external_id": "lot-1", "title": "Lote 1 novo", "status": "live", "total_bids": 3})
    db.commit()
    assert created2 is False
    assert lot2.id == lot.id
    assert lot2.first_seen_at == first_seen
    assert lot2.last_seen_at >= first_last_seen
    assert lot2.total_bids == 3
    assert lot2.status == "live"


def test_list_upcoming_lots_filters_and_orders(db):
    now = datetime.now(timezone.utc)
    upsert_lot(db, {"source": "copart_auctions", "external_id": "past", "auction_end_at": now - timedelta(hours=1), "status": "live"})
    upsert_lot(db, {"source": "copart_auctions", "external_id": "future-2", "auction_end_at": now + timedelta(hours=2), "status": "scheduled"})
    upsert_lot(db, {"source": "copart_auctions", "external_id": "future-1", "auction_end_at": now + timedelta(hours=1), "status": "scheduled"})
    db.commit()

    lots = list_upcoming_lots(db, limit=10)
    ids = [l.external_id for l in lots]
    assert "past" not in ids
    assert ids == ["future-1", "future-2"]


def test_list_by_source_motorcycle_and_stats(db):
    upsert_lot(db, {"source": "copart_auctions", "external_id": "c1", "item_type": "car", "status": "scheduled"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "v1", "item_type": "motorcycle", "status": "live"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "v2", "item_type": "motorcycle", "status": "sold"})
    db.commit()

    vip_lots = list_lots_by_source(db, "vip_auctions", limit=10)
    assert {x.external_id for x in vip_lots} == {"v1", "v2"}

    moto_lots = list_motorcycle_lots(db, limit=10)
    assert {x.external_id for x in moto_lots} == {"v1", "v2"}

    stats = get_auction_stats(db)
    assert stats["total_lots"] == 3
    assert stats["by_source"]["vip_auctions"] == 2
    assert stats["by_status"]["scheduled"] == 1
