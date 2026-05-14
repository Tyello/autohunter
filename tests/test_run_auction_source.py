import sys
import types

from app.sources.auctions.base import NormalizedAuctionLot
from scripts.run_auction_source import run


def test_run_dry_run_does_not_import_db_modules(monkeypatch):
    monkeypatch.setattr("scripts.run_auction_source.fetch_copart_lots", lambda limit: [NormalizedAuctionLot(source="copart_auctions", external_id="1")])
    sys.modules.pop("app.db.session", None)
    sys.modules.pop("app.services.auction_lot_service", None)
    run(source="copart_auctions", limit=1, dry_run=True)
    assert "app.db.session" not in sys.modules
    assert "app.services.auction_lot_service" not in sys.modules


def test_run_persistent_calls_upsert(monkeypatch):
    lots = [NormalizedAuctionLot(source="copart_auctions", external_id="1")]
    monkeypatch.setattr("scripts.run_auction_source.fetch_copart_lots", lambda limit: lots)

    calls = {"n": 0}

    def fake_upsert(db, payload):
        calls["n"] += 1
        return object(), True

    class FakeSession:
        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    fake_db_module = types.SimpleNamespace(SessionLocal=lambda: FakeSession())
    fake_service_module = types.SimpleNamespace(upsert_lot=fake_upsert)
    monkeypatch.setitem(sys.modules, "app.db.session", fake_db_module)
    monkeypatch.setitem(sys.modules, "app.services.auction_lot_service", fake_service_module)

    run(source="copart_auctions", limit=1, dry_run=False)
    assert calls["n"] == 1
