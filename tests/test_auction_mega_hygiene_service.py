from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models.auction_lot import AuctionLot
from app.models.source_config import SourceConfig
from app.services.auction_mega_hygiene_service import run_mega_hygiene


def _mk_lot(db, external_id, url, item_type="car", city=None, state=None, location=None):
    lot = AuctionLot(
        id=uuid.uuid4(),
        source="mega_auctions",
        external_id=external_id,
        url=url,
        title="Honda Civic",
        item_type=item_type,
        city=city,
        state=state,
        location=location,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(lot)
    db.commit()
    return lot


def test_run_mega_hygiene_dry_run_reports_issues_without_mutating(db):
    _mk_lot(db, "ext-1", "https://mega.com.br/veiculos/motos/123", item_type="car")

    result = run_mega_hygiene(db, apply=False)

    assert result["dry_run"] is True
    assert result["analyzed"] == 1
    assert result["issue_counts"].get("motorcycle_mismatch") == 1
    assert result["updated"] == 0

    lot = db.query(AuctionLot).filter(AuctionLot.external_id == "ext-1").one()
    assert lot.item_type == "car"


def test_run_mega_hygiene_apply_blocked_when_source_not_experimental(db):
    db.add(SourceConfig(source="mega_auctions", source_type="auction", status="production_ready"))
    db.commit()
    _mk_lot(db, "ext-2", "https://mega.com.br/veiculos/motos/123", item_type="car")

    result = run_mega_hygiene(db, apply=True)

    assert result["blocked"] is True
    assert result["reason"] == "source_not_experimental"
    assert result["updated"] == 0

    lot = db.query(AuctionLot).filter(AuctionLot.external_id == "ext-2").one()
    assert lot.item_type == "car"


def test_run_mega_hygiene_apply_updates_when_experimental(db):
    db.add(SourceConfig(source="mega_auctions", source_type="auction", status="experimental"))
    db.commit()
    _mk_lot(db, "ext-3", "https://mega.com.br/veiculos/motos/123", item_type="car")

    result = run_mega_hygiene(db, apply=True)

    assert result["blocked"] is False
    assert result["updated"] == 1

    lot = db.query(AuctionLot).filter(AuctionLot.external_id == "ext-3").one()
    assert lot.item_type == "motorcycle"


def test_run_mega_hygiene_no_issues_for_clean_lot(db):
    _mk_lot(db, "ext-4", "https://mega.com.br/veiculos/carros/j1234-honda-civic", item_type="car")

    result = run_mega_hygiene(db, apply=False)

    assert result["issue_counts"] == {}
    assert result["examples"] == []
