from __future__ import annotations

from app.repositories.car_listings_repo import _dedupe_listings


def test_dedupe_merges_best_fields_and_keeps_latest_url():
    listings = [
        {
            "source": "mercadolivre",
            "external_id": "MLB1",
            "title": None,
            "thumbnail_url": None,
            "price": None,
            "location": None,
            "url": "https://carro.mercadolivre.com.br/MLB-1-old-_JM",
        },
        {
            "source": "mercadolivre",
            "external_id": "MLB1",
            "title": "Honda Civic Hatch SI 1994",
            "thumbnail_url": "https://http2.mlstatic.com/D_Q_NP_2X_foo.webp",
            "price": 85900,
            "location": "Curitiba, PR",
            "url": "https://carro.mercadolivre.com.br/MLB-1-new-_JM",
        },
    ]

    out = _dedupe_listings(listings)
    assert len(out) == 1
    item = out[0]
    assert item["title"] == "Honda Civic Hatch SI 1994"
    assert item["thumbnail_url"] is not None
    assert item["price"] == 85900
    assert item["location"] == "Curitiba, PR"
    assert item["url"] == "https://carro.mercadolivre.com.br/MLB-1-new-_JM"


def test_dedupe_drops_items_without_key():
    out = _dedupe_listings([
        {"source": None, "external_id": "1", "url": "x"},
        {"source": "olx", "external_id": None, "url": "y"},
        {"source": "olx", "external_id": "OLX1", "url": "z"},
    ])
    assert len(out) == 1
    assert out[0]["external_id"] == "OLX1"
