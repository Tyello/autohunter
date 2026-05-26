from app.repositories import car_listings_repo


def test_homogenize_bulk_insert_rows_fills_missing_keys_with_none():
    rows = [
        {"source": "mercadolivre", "external_id": "1", "cross_source_fingerprint": "fp"},
        {"source": "mercadolivre", "external_id": "2"},
    ]

    out = car_listings_repo._homogenize_bulk_insert_rows(rows)

    assert len(out) == 2
    assert set(out[0].keys()) == set(out[1].keys())
    assert "cross_source_fingerprint" in out[1]
    assert out[1]["cross_source_fingerprint"] is None


def test_homogenize_bulk_insert_rows_uses_only_union_of_input_keys():
    rows = [
        {"source": "mercadolivre", "external_id": "1", "year": 2020},
        {"source": "mercadolivre", "external_id": "2", "mileage_km": 50000, "color": "preto"},
    ]

    out = car_listings_repo._homogenize_bulk_insert_rows(rows)
    union_keys = {"source", "external_id", "year", "mileage_km", "color"}

    assert set(out[0].keys()) == union_keys
    assert set(out[1].keys()) == union_keys
    assert "title" not in out[0]
    assert out[0]["mileage_km"] is None
    assert out[1]["year"] is None


def test_insert_ignore_duplicates_accepts_mixed_cross_source_fingerprint_rows(db, monkeypatch):
    responses = iter(["fp1", None])

    def _fake_fp(_listing):
        return next(responses)

    monkeypatch.setattr(car_listings_repo, "compute_cross_source_fingerprint", _fake_fp)

    payload = [
        {
            "source": "mercadolivre",
            "external_id": "ml1",
            "title": "Carro 1",
            "url": "https://example.com/1",
        },
        {
            "source": "mercadolivre",
            "external_id": "ml2",
            "title": "Carro 2",
            "url": "https://example.com/2",
        },
    ]

    captured = {}
    real_execute = db.execute

    class _Result:
        def fetchall(self):
            return []

    def _capture_execute(stmt, *args, **kwargs):
        captured["stmt"] = stmt
        return _Result()

    monkeypatch.setattr(db, "execute", _capture_execute)

    car_listings_repo.insert_ignore_duplicates_return_ids(db, payload)

    values = captured["stmt"].compile().params
    assert values["cross_source_fingerprint_m0"] == "fp1"
    assert values["cross_source_fingerprint_m1"] is None

    monkeypatch.setattr(db, "execute", real_execute)
