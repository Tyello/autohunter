from __future__ import annotations

from decimal import Decimal

from app.services import listings_service


def test_sanitize_price_handles_ptbr_and_rejects_out_of_range():
    assert listings_service._sanitize_price("R$ 123.456,78") == Decimal("123456.78")
    assert listings_service._sanitize_price("0") is None
    assert listings_service._sanitize_price("999999999999999") is None


def test_ingest_listings_stats_uses_repo_with_stats(monkeypatch):
    captured = {}

    def _fake_repo(_db, payload, with_stats=False):
        captured["payload"] = payload
        captured["with_stats"] = with_stats
        return {
            "ids": ["a", "b"],
            "inserted_new": 1,
            "updated": 1,
            "upserted": 2,
        }

    monkeypatch.setattr(listings_service, "insert_ignore_duplicates_return_ids", _fake_repo)

    res = listings_service.ingest_listings_stats(
        db=object(),
        listings=[{"source": "olx", "external_id": "1", "url": "https://x", "price": "R$ 89.999,90"}],
    )

    assert captured["with_stats"] is True
    assert captured["payload"][0]["price"] == Decimal("89999.90")
    assert res.inserted_new == 1
    assert res.updated == 1
    assert res.upserted == 2


def test_ingest_listings_stats_falls_back_when_repo_does_not_support_with_stats(monkeypatch):
    calls = {"n": 0}

    def _fake_repo(_db, _payload, with_stats=False):
        calls["n"] += 1
        if with_stats:
            raise TypeError("legacy repo")
        return ["id-1", "id-2"]

    monkeypatch.setattr(listings_service, "insert_ignore_duplicates_return_ids", _fake_repo)

    res = listings_service.ingest_listings_stats(
        db=object(),
        listings=[{"source": "olx", "external_id": "1", "url": "https://x", "price": "95.000"}],
    )

    assert calls["n"] == 2
    assert res.ids == ["id-1", "id-2"]
    assert res.inserted_new == 2
    assert res.updated == 0
    assert res.upserted == 2
