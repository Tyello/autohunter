import pytest

from app.models.source_run import SourceRun
from app.db.session import SessionLocal as RealSessionLocal
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

    class _Q:
        def filter(self, *_args, **_kwargs):
            return self
        def first(self):
            return None
    class FakeDB:
        def query(self, *_args, **_kwargs): return _Q()
        def add(self, *_args, **_kwargs): return None
        def flush(self): return None
        def commit(self): calls["committed"] = True
        def rollback(self): calls["rollback"] = True
        def close(self): calls["closed"] = True

    def _fetch(limit, enrich=False):
        calls["enrich"] = enrich
        return [NormalizedAuctionLot(source="vip_auctions", external_id="1", title="Honda", url="https://x/item/1", year=2020)]

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("vip_auctions", _fetch, lambda: "x", True))
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))
    monkeypatch.setattr(svc, "record_run", lambda *args, **kwargs: calls.__setitem__("recorded", True))

    out = svc.run_auction_ingestion("vip_auctions", limit=10, enrich_details=True)
    assert out["fetched"] == 1
    assert out["inserted"] == 1
    assert calls["committed"] is True
    assert calls["enrich"] is True
    assert calls["recorded"] is True


def test_run_auction_ingestion_rollback_on_error(monkeypatch):
    calls = {"rolled": False}

    class FakeDB:
        def commit(self): return None
        def rollback(self): calls["rolled"] = True
        def close(self): return None

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("vip_auctions", lambda limit, enrich=False: [NormalizedAuctionLot(source="vip_auctions", external_id="1", title="Honda", url="https://x/item/1", year=2020)], lambda: None, True))

    def boom(_db, _payload):
        raise RuntimeError("x")

    monkeypatch.setattr(svc, "upsert_lot", boom)
    with pytest.raises(RuntimeError):
        svc.run_auction_ingestion("vip_auctions", limit=10, enrich_details=False)
    assert calls["rolled"] is True


def test_run_auction_ingestion_records_error_run_and_reraises(monkeypatch, db):
    monkeypatch.setattr(svc, "SessionLocal", RealSessionLocal)
    monkeypatch.setattr(
        svc,
        "get_auction_source_definition",
        lambda _s: _Def("win_auctions", lambda limit, enrich=False: (_ for _ in ()).throw(RuntimeError("fetch failed")), lambda: None, True),
    )
    with pytest.raises(RuntimeError):
        svc.run_auction_ingestion("win_auctions", limit=10, enrich_details=False)
    row = db.query(SourceRun).filter(SourceRun.source == "win_auctions").order_by(SourceRun.created_at.desc()).first()
    assert row is not None
    assert row.status == "error"
    payload = row.payload or {}
    summary = payload.get("auction_summary") or {}
    assert summary.get("errors") == 1
    assert summary.get("error_type") == "RuntimeError"


def test_run_auction_ingestion_sodre_without_enrich(monkeypatch):
    called = {"enrich_used": False}

    class FakeDB:
        def commit(self): return None
        def rollback(self): return None
        def close(self): return None

    def _fetch(limit):
        called["enrich_used"] = False
        return [NormalizedAuctionLot(source="sodre_auctions", external_id="s1", title="Yamaha", url="https://x/item/s1", year=2020)]

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
    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("superbid_auctions", lambda limit: [NormalizedAuctionLot(source="superbid_auctions", external_id="sb1", title="Yamaha", url="https://x/item/sb1", year=2020)], lambda: None, False))
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))
    out = svc.run_auction_ingestion("superbid_auctions", limit=10, enrich_details=True)
    assert out["source"] == "superbid_auctions"


def test_run_auction_ingestion_skips_invalid_and_counts_reasons(monkeypatch):
    class FakeDB:
        def commit(self): return None
        def rollback(self): return None
        def close(self): return None

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(
        svc,
        "get_auction_source_definition",
        lambda _s: _Def(
            "vip_auctions",
            lambda limit, enrich=False: [
                NormalizedAuctionLot(source="vip_auctions", external_id="1", title="Sem título", url="-"),
                NormalizedAuctionLot(source="vip_auctions", external_id="2", title="Honda CG", url="https://ok/item/2", year=2022),
            ],
            lambda: None,
            True,
        ),
    )
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))
    out = svc.run_auction_ingestion("vip_auctions", limit=10, enrich_details=False)
    assert out["inserted"] == 1
    assert out["skipped"] == 1
    assert out["skipped_reasons"]["invalid_url"] == 1


def test_run_auction_ingestion_collects_ignored_examples(monkeypatch):
    class FakeDB:
        def commit(self): return None
        def rollback(self): return None
        def close(self): return None

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(
        svc,
        "get_auction_source_definition",
        lambda _s: _Def(
            "win_auctions",
            lambda limit: [
                NormalizedAuctionLot(
                    source="win_auctions",
                    external_id="w1",
                    title=None,
                    url="https://win/item/1",
                    raw_payload={"html_card": "<div>texto do card</div>"},
                    extras={"event_title": "Fallback Win"},
                )
            ],
            lambda: None,
            False,
        ),
    )
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))
    out = svc.run_auction_ingestion("win_auctions", limit=10, enrich_details=False)
    assert out["skipped"] == 1
    assert out["ignored_examples"]
    ex = out["ignored_examples"][0]
    assert ex["reason"] == "missing_title"
    assert ex["url"] == "https://win/item/1"
    assert ex["fallback_title"] == "Fallback Win"
    assert "texto do card" in ex["text_preview"]


def test_inspect_auction_source_does_not_persist(monkeypatch):
    called = {"upsert": 0}

    def _fetch(limit):
        return [NormalizedAuctionLot(source="vip_auctions", external_id="1", title="Honda Civic 2018", url="https://x/item/1", year=2018)]

    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("vip_auctions", _fetch, lambda: None, False))
    monkeypatch.setattr(svc, "upsert_lot", lambda *_args, **_kwargs: called.__setitem__("upsert", called["upsert"] + 1))

    out = svc.inspect_auction_source("vip_auctions", limit=5, enrich_details=False)
    assert out["fetched"] == 1
    assert called["upsert"] == 0


def test_inspect_auction_source_win_detail_url_external_id_and_no_persist(monkeypatch):
    called = {"upsert": 0}

    class _Resp:
        status_code = 200
        url = "https://www.winleiloes.com.br/item/4042/detalhes?page=1"
        headers = {"content-type": "text/html"}
        text = "<html><head><title>Gol 2015</title></head><body>Lance Inicial: R$ 10.000,00</body></html>"
        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def get(self, _url):
            return _Resp()

    monkeypatch.setattr(svc.httpx, "Client", _Client)
    monkeypatch.setattr(svc, "upsert_lot", lambda *_args, **_kwargs: called.__setitem__("upsert", called["upsert"] + 1))
    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("win_auctions", lambda limit, enrich=False: [], lambda: None, True))

    out = svc.inspect_auction_source("win_auctions", detail_url="https://www.winleiloes.com.br/item/4042/detalhes?page=1")
    assert out["fetched"] == 1
    assert out["candidates"][0]["external_id"] == "4042"
    assert called["upsert"] == 0
    win_diag = (((out.get("diagnostics") or {}).get("detail_diagnostics") or {}).get("win_detail") or {})
    assert "status_candidates" in win_diag


def test_inspect_auction_source_detail_url_unsupported_source_returns_reason(monkeypatch):
    class _Resp:
        status_code = 200
        url = "https://example.com/item/1"
        headers = {"content-type": "text/html"}
        text = "<html><body>ok</body></html>"
    class _Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def get(self, _url):
            return _Resp()
    monkeypatch.setattr(svc.httpx, "Client", _Client)
    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("vip_auctions", lambda limit, enrich=False: [], lambda: None, True))
    out = svc.inspect_auction_source("vip_auctions", detail_url="https://example.com/item/1")
    assert out["fetched"] == 0
    assert out["reason"] == "detail_inspect_not_supported_for_source"


def test_inspect_auction_source_mega_detail_includes_diagnostics(monkeypatch):
    class _Resp:
        status_code = 200
        url = "https://www.megaleiloes.com.br/veiculos/carros/sp/atibaia/x-j122290"
        headers = {"content-type": "text/html"}
        text = "<html><head><meta property='og:image' content='https://cdn.mega/car.jpg'></head><body><h1>Volkswagen Kombi 1999</h1><div>Status: encerrado</div></body></html>"
    class _Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def get(self, _url):
            return _Resp()
    monkeypatch.setattr(svc.httpx, "Client", _Client)
    monkeypatch.setattr(svc, "get_auction_source_definition", lambda _s: _Def("mega_auctions", lambda limit, enrich=False: [], lambda: None, True))
    out = svc.inspect_auction_source("mega_auctions", detail_url=_Resp.url)
    assert out["fetched"] == 1
    mega_diag = (((out.get("diagnostics") or {}).get("detail_diagnostics") or {}).get("mega_detail") or {})
    assert "status_candidates" in mega_diag


def test_run_auction_ingestion_does_not_include_detail_diagnostics(monkeypatch):
    class FakeDB:
        def commit(self): return None
        def rollback(self): return None
        def close(self): return None

    monkeypatch.setattr(svc, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(
        svc,
        "get_auction_source_definition",
        lambda _s: _Def("win_auctions", lambda limit, enrich=False: [NormalizedAuctionLot(source="win_auctions", external_id="1", title="Civic", url="https://x/1", year=2020)], lambda: None, True),
    )
    monkeypatch.setattr(svc, "upsert_lot", lambda db, payload: (object(), True))
    out = svc.run_auction_ingestion("win_auctions", limit=1, enrich_details=True)
    assert "diagnostics" not in out


def test_upsert_win_clears_stale_invalid_location_on_none(db):
    from app.services.auction_lot_service import upsert_lot

    upsert_lot(db, {"source": "win_auctions", "external_id": "4077", "location": "CAOA CHERY / CE", "city": "CAOA CHERY", "state": "CE", "url": "https://win/4077"})
    db.commit()
    lot, _ = upsert_lot(db, {"source": "win_auctions", "external_id": "4077", "location": None, "city": None, "state": None, "url": "https://win/4077"})
    db.commit()
    assert lot.location is None
    assert lot.city is None
    assert lot.state is None


def test_upsert_win_preserves_valid_location_when_still_valid(db):
    from app.services.auction_lot_service import upsert_lot

    upsert_lot(db, {"source": "win_auctions", "external_id": "5001", "location": "Curitiba/PR", "city": "Curitiba", "state": "PR", "url": "https://win/5001"})
    db.commit()
    lot, _ = upsert_lot(db, {"source": "win_auctions", "external_id": "5001", "location": "Curitiba/PR", "city": "Curitiba", "state": "PR", "url": "https://win/5001"})
    db.commit()
    assert lot.location == "Curitiba/PR"
    assert lot.city == "Curitiba"
    assert lot.state == "PR"
