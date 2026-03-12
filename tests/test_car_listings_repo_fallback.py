from __future__ import annotations

from decimal import Decimal

from sqlalchemy.dialects.postgresql.dml import Insert

from app.models.car_listing import CarListing
from app.repositories import car_listings_repo


def test_insert_ignore_duplicates_falls_back_without_unique_constraint(db, monkeypatch):
    calls = {"n": 0}
    real_execute = db.execute

    class _Orig:
        def __str__(self):
            return "there is no unique or exclusion constraint matching the ON CONFLICT specification"

    def _fake_execute(_stmt, *args, **kwargs):
        if isinstance(_stmt, Insert):
            calls["n"] += 1
            raise car_listings_repo.ProgrammingError("stmt", {}, _Orig())
        return real_execute(_stmt, *args, **kwargs)

    monkeypatch.setattr(db, "execute", _fake_execute)

    payload = [
        {
            "source": "chavesnamao",
            "external_id": "abc123",
            "title": "Audi A5",
            "url": "https://example.com/a5",
            "price": Decimal("100000.00"),
            "currency": "BRL",
            "listing_type": "marketplace",
            "extras": {},
        }
    ]

    res = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload, with_stats=True)

    row = db.query(CarListing).filter_by(source="chavesnamao", external_id="abc123").one()
    assert calls["n"] == 1
    assert row.title == "Audi A5"
    assert res["inserted_new"] == 1
    assert res["updated"] == 0
    assert res["upserted"] == 1
