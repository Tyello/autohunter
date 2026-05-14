from app.sources.auctions.base import NormalizedAuctionLot
from scripts.run_auction_source import run


def test_run_dry_run_does_not_persist(monkeypatch):
    called = {"upsert": 0}
    monkeypatch.setattr("scripts.run_auction_source.fetch_copart_lots", lambda limit: [NormalizedAuctionLot(source="copart_auctions", external_id="1")])
    monkeypatch.setattr("scripts.run_auction_source.upsert_lot", lambda *args, **kwargs: called.__setitem__("upsert", called["upsert"] + 1))
    run(source="copart_auctions", limit=1, dry_run=True)
    assert called["upsert"] == 0


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

    monkeypatch.setattr("scripts.run_auction_source.upsert_lot", fake_upsert)
    monkeypatch.setattr("scripts.run_auction_source.SessionLocal", lambda: FakeSession())
    run(source="copart_auctions", limit=1, dry_run=False)
    assert calls["n"] == 1
