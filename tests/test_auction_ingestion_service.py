import pytest

from app.sources.auctions.base import NormalizedAuctionLot
from app.services import auction_ingestion_service as svc


def test_run_auction_ingestion_vip_enrich_and_summary(monkeypatch):
    calls = {"enrich": None, "committed": False}

    class FakeDB:
        def commit(self):
            calls["committed"] = True
        def rollback(self):
            calls["rollback"] = True
        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(svc, "fetch_vip_lots", lambda limit, enrich=False: [NormalizedAuctionLot(source="vip_auctions", external_id="1")])
    monkeypatch.setattr(svc, "vip_reason", lambda: "x")
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))

    out = svc.run_auction_ingestion("vip_auctions", limit=10, enrich_details=True)
    assert out["fetched"] == 1
    assert out["inserted"] == 1
    assert calls["committed"] is True


def test_run_auction_ingestion_rollback_on_error(monkeypatch):
    calls = {"rolled": False}

    class FakeDB:
        def commit(self):
            return None
        def rollback(self):
            calls["rolled"] = True
        def close(self):
            return None

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(svc, "fetch_vip_lots", lambda limit, enrich=False: [NormalizedAuctionLot(source="vip_auctions", external_id="1")])
    monkeypatch.setattr(svc, "vip_reason", lambda: None)

    def boom(_db, _payload):
        raise RuntimeError("x")

    monkeypatch.setattr(svc, "upsert_lot", boom)
    with pytest.raises(RuntimeError):
        svc.run_auction_ingestion("vip_auctions", limit=10, enrich_details=False)
    assert calls["rolled"] is True


def test_run_auction_ingestion_mega(monkeypatch):
    class FakeDB:
        def commit(self):
            return None
        def rollback(self):
            return None
        def close(self):
            return None

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(svc, "fetch_mega_lots", lambda limit: [NormalizedAuctionLot(source="mega_auctions", external_id="m1")])
    monkeypatch.setattr(svc, "mega_reason", lambda: None)
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))
    out = svc.run_auction_ingestion("mega_auctions", limit=10, enrich_details=False)
    assert out["source"] == "mega_auctions"
    assert out["inserted"] == 1


def test_run_auction_ingestion_win(monkeypatch):
    class FakeDB:
        def commit(self):
            return None
        def rollback(self):
            return None
        def close(self):
            return None

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(svc, "fetch_win_lots", lambda limit: [NormalizedAuctionLot(source="win_auctions", external_id="w1")])
    monkeypatch.setattr(svc, "win_reason", lambda: None)
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))
    out = svc.run_auction_ingestion("win_auctions", limit=10, enrich_details=False)
    assert out["source"] == "win_auctions"
    assert out["inserted"] == 1
