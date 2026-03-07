from app.scrapers.sources.gogarage_mobiauto import MobiautoScraper


def test_mobiauto_v2_parse_listing_uses_detail_id_as_external_id():
    scraper = MobiautoScraper()
    parsed = scraper.parse_listing(
        {
            "url": "https://www.mobiauto.com.br/comprar/carros/sp-sao-paulo/honda-civic/2.0-16v-flexone-exl-4p-cvt/4-portas/2018-2019/70113402/detalhes?page=detail&sop=showroom",
            "title": "Honda Civic EXL",
            "price": "R$ 90.000",
            "year": "2019",
            "mileage": "80.000 km",
            "thumbnail": "https://img.example/civic.jpg",
        }
    )

    assert parsed is not None
    assert parsed["external_id"] == "70113402"


def test_mobiauto_v2_parse_listing_hash_fallback_when_detail_id_is_missing():
    scraper = MobiautoScraper()
    parsed = scraper.parse_listing(
        {
            "url": "https://www.mobiauto.com.br/comprar/carros?q=civic",
            "title": "Honda Civic",
        }
    )

    assert parsed is not None
    assert len(parsed["external_id"]) == 16
