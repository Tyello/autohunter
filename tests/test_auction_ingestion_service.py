import pytest

from app.sources.auctions.base import NormalizedAuctionLot
from app.services import auction_ingestion_service as svc


class _Def:
    def __init__(self, key, fetcher, reason_getter, supports_enrich=False):
        self.key = key
        self.fetcher = fetcher
        self.reason_getter = reason_getter
        self.supports_enrich = supports_enrich


def test_run_auction_ingestion_vip_enrich_and_summary(monkeypatch):
    calls = {"committed": False, "enrich": None}

    class FakeDB:
        def commit(self): calls["committed"] = True
        def rollback(self): calls["rollback"] = True
        def close(self): calls["closed"] = True

    def _fetch(limit, enrich=False):
        calls["enrich"] = enrich
        return [NormalizedAuctionLot(source="vip_auctions", external_id="1")]

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("vip_auctions", _fetch, lambda: "x", True))
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))

    out = svc.run_auction_ingestion("vip_auctions", limit=10, enrich_details=True)
    assert out["fetched"] == 1
    assert out["inserted"] == 1
    assert calls["committed"] is True
    assert calls["enrich"] is True


def test_run_auction_ingestion_rollback_on_error(monkeypatch):
    calls = {"rolled": False}

    class FakeDB:
        def commit(self): return None
        def rollback(self): calls["rolled"] = True
        def close(self): return None

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("vip_auctions", lambda limit, enrich=False: [NormalizedAuctionLot(source="vip_auctions", external_id="1")], lambda: None, True))

    def boom(_db, _payload):
        raise RuntimeError("x")

    monkeypatch.setattr(svc, "upsert_lot", boom)
    with pytest.raises(RuntimeError):
        svc.run_auction_ingestion("vip_auctions", limit=10, enrich_details=False)
    assert calls["rolled"] is True


def test_run_auction_ingestion_sodre_without_enrich(monkeypatch):
    called = {"enrich_used": False}

    class FakeDB:
        def commit(self): return None
        def rollback(self): return None
        def close(self): return None

    def _fetch(limit):
        called["enrich_used"] = False
        return [NormalizedAuctionLot(source="sodre_auctions", external_id="s1")]

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("sodre_auctions", _fetch, lambda: None, False))
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))
    out = svc.run_auction_ingestion("sodre_auctions", limit=10, enrich_details=True)
    assert out["source"] == "sodre_auctions"


def test_run_auction_ingestion_superbid_without_enrich(monkeypatch):
    class FakeDB:
        def commit(self): return None
        def rollback(self): return None
        def close(self): return None

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("superbid_auctions", lambda limit: [NormalizedAuctionLot(source="superbid_auctions", external_id="sb1")], lambda: None, False))
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))
    out = svc.run_auction_ingestion("superbid_auctions", limit=10, enrich_details=True)
    assert out["source"] == "superbid_auctions"
