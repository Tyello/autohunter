from app.sources.auctions.base import NormalizedAuctionLot
from scripts.run_auction_source import run


class _Def:
    def __init__(self, key, fetcher, reason_getter, supports_enrich=False):
        self.key = key
        self.fetcher = fetcher
        self.reason_getter = reason_getter
        self.supports_enrich = supports_enrich


def test_run_persistent_calls_upsert(monkeypatch):
    calls = {"n": 0}

    def fake_run_ingestion(**kwargs):
        calls["n"] += 1
        return {"source": "vip_auctions", "fetched": 1, "inserted": 1, "updated": 0, "skipped": 0, "errors": 0, "reason": None}

    monkeypatch.setattr("scripts.run_auction_source.resolve_auction_source_alias", lambda s: "vip_auctions")
    monkeypatch.setattr("scripts.run_auction_source.run_auction_ingestion", fake_run_ingestion)
    run(source="vip_auctions", limit=1, dry_run=False)
    assert calls["n"] == 1


def test_invalid_source_raises_clear_error(monkeypatch):
    monkeypatch.setattr("scripts.run_auction_source.resolve_auction_source_alias", lambda s: None)
    try:
        run(source="invalid_source", limit=1, dry_run=True)
    except ValueError as exc:
        assert "Unsupported source" in str(exc)
        assert "Use: vip|mega|win|copart" in str(exc)
    else:
        assert False, "Expected ValueError"


def test_run_enrich_details_passed_to_vip(monkeypatch):
    called = {"enrich": None}

    def fake_fetch(limit, enrich=False):
        called["enrich"] = enrich
        return [NormalizedAuctionLot(source="vip_auctions", external_id="1")]

    monkeypatch.setattr("scripts.run_auction_source.resolve_auction_source_alias", lambda s: "vip_auctions")
    monkeypatch.setattr("scripts.run_auction_source.get_auction_source_definition", lambda s: _Def("vip_auctions", fake_fetch, lambda: None, True))
    run(source="vip_auctions", limit=1, dry_run=True, enrich_details=True)
    assert called["enrich"] is True


def test_run_dry_run_mega(monkeypatch):
    monkeypatch.setattr("scripts.run_auction_source.resolve_auction_source_alias", lambda s: "mega_auctions")
    monkeypatch.setattr("scripts.run_auction_source.get_auction_source_definition", lambda s: _Def("mega_auctions", lambda limit: [NormalizedAuctionLot(source="mega_auctions", external_id="m1")], lambda: None, False))
    run(source="mega_auctions", limit=1, dry_run=True)
