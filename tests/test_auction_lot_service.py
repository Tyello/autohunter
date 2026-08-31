from __future__ import annotations

from app.services.auction_lot_service import (
    upsert_lot,
)


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
