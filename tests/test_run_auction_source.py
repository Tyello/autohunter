import sys
import types

from app.sources.auctions.base import NormalizedAuctionLot
from scripts.run_auction_source import run


def test_run_dry_run_does_not_import_db_modules(monkeypatch):
    monkeypatch.setattr("scripts.run_auction_source.fetch_vip_lots", lambda limit, enrich=False: [NormalizedAuctionLot(source="vip_auctions", external_id="1")])
    sys.modules.pop("app.db.session", None)
    sys.modules.pop("app.services.auction_lot_service", None)
    run(source="vip_auctions", limit=1, dry_run=True)
    assert "app.db.session" not in sys.modules
    assert "app.services.auction_lot_service" not in sys.modules


def test_run_persistent_calls_upsert(monkeypatch):
    calls = {"n": 0}

    def fake_run_ingestion(**kwargs):
        calls["n"] += 1
        return {"source": "vip_auctions", "fetched": 1, "inserted": 1, "updated": 0, "skipped": 0, "errors": 0, "reason": None}

    monkeypatch.setattr("scripts.run_auction_source.run_auction_ingestion", fake_run_ingestion)
    run(source="vip_auctions", limit=1, dry_run=False)
    assert calls["n"] == 1


def test_invalid_source_raises_clear_error():
    try:
        run(source="invalid_source", limit=1, dry_run=True)
    except ValueError as exc:
        assert "Unsupported source" in str(exc)
        assert "copart_auctions" in str(exc)
        assert "vip_auctions" in str(exc)
        assert "mega_auctions" in str(exc)
    else:
        assert False, "Expected ValueError"


def test_run_enrich_details_passed_to_vip(monkeypatch):
    called = {"enrich": None}

    def fake_fetch(limit, enrich=False):
        called["enrich"] = enrich
        return [NormalizedAuctionLot(source="vip_auctions", external_id="1")]

    monkeypatch.setattr("scripts.run_auction_source.fetch_vip_lots", fake_fetch)
    run(source="vip_auctions", limit=1, dry_run=True, enrich_details=True)
    assert called["enrich"] is True


def test_run_dry_run_mega(monkeypatch):
    monkeypatch.setattr("scripts.run_auction_source.fetch_mega_lots", lambda limit: [NormalizedAuctionLot(source="mega_auctions", external_id="m1")])
    run(source="mega_auctions", limit=1, dry_run=True)
