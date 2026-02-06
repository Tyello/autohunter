from app.scrapers.contract import finalize_listings


def test_finalize_listings_fills_currency_and_external_id():
    raw = [
        {
            "source": "mercadolivre",
            "external_id": "",
            "url": "https://carro.mercadolivre.com.br/MLB-1234567890?utm_source=x#frag",
            "title": "  Honda  Civic   Si  ",
            "price": 123,
        }
    ]

    out = finalize_listings("mercadolivre", raw)
    assert len(out) == 1
    assert out[0]["currency"] == "BRL"
    assert out[0]["external_id"] == "MLB1234567890"
    assert out[0]["url"].endswith("MLB-1234567890")
    assert out[0]["title"] == "Honda Civic Si"


def test_finalize_listings_dedupes_by_source_and_external_id():
    raw = [
        {"source": "olx", "external_id": "1", "url": "https://www.olx.com.br/a?utm=1", "title": "A"},
        {"source": "olx", "external_id": "1", "url": "https://www.olx.com.br/a", "title": None, "price": 10},
    ]

    out = finalize_listings("olx", raw)
    assert len(out) == 1
    assert out[0]["url"] == "https://www.olx.com.br/a"
    assert out[0]["title"] == "A"
    assert out[0]["price"] == 10
