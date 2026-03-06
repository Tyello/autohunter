from app.scrapers.scraper_base.metrics import PipelineMetrics
from app.scrapers.scraper_base.scraper import ScraperResult
from app.sources.ad_quality import QualitySeverity, enforce_ad_contract
from app.sources.adapters.v2 import adapt_v2
from app.sources.normalize import normalize_ad


def _mk_ad(**overrides):
    payload = {
        "source": "olx",
        "external_id": "abc-1",
        "url": "https://example.com/car/1",
        "title": "  Civic   EXL  ",
        "price": 95000,
        "city": " São Paulo ",
        "uf": "sp",
        "year": 2020,
        "mileage_km": 42000,
        "images": [
            "https://img.example/1.jpg",
            "https://img.example/2.jpg",
        ],
    }
    payload.update(overrides)
    ad = normalize_ad("olx", payload)
    return enforce_ad_contract(ad)


def test_valid_complete_ad():
    res = _mk_ad()
    assert res.severity == QualitySeverity.INFO
    assert res.quality_flags == ()
    assert res.ad.title == "Civic EXL"
    assert res.ad.city == "São Paulo"
    assert res.ad.uf == "SP"
    assert res.ad.images_count == 2


def test_missing_price():
    res = _mk_ad(price=None)
    assert "missing_price" in res.quality_flags
    assert res.severity == QualitySeverity.WARNING


def test_missing_images():
    res = _mk_ad(images=[])
    assert "missing_images" in res.quality_flags
    assert res.ad.images_count == 0


def test_invalid_url_is_critical():
    res = _mk_ad(url="notaurl")
    assert ("invalid_url" in res.quality_flags) or ("missing_url" in res.quality_flags)
    assert res.severity == QualitySeverity.CRITICAL


def test_empty_title_is_critical():
    res = _mk_ad(title="   ")
    assert "empty_title" in res.quality_flags
    assert res.severity == QualitySeverity.CRITICAL


def test_suspect_year():
    res = _mk_ad(year=1940)
    assert "suspect_year" in res.quality_flags
    assert res.severity == QualitySeverity.WARNING


def test_suspect_km():
    res = _mk_ad(mileage_km=2_000_000)
    assert "suspect_km" in res.quality_flags


def test_incomplete_location():
    res = _mk_ad(city="Campinas", uf=None)
    assert "incomplete_location" in res.quality_flags


def test_duplicate_images_are_deduped():
    res = _mk_ad(images=["https://img.example/1.jpg", "https://img.example/1.jpg", "bad"])
    assert "duplicate_images" in res.quality_flags
    assert "broken_images" in res.quality_flags
    assert res.ad.images_count == 1
    assert res.ad.extras["image_urls"] == ["https://img.example/1.jpg"]


def test_integration_adapter_v2_applies_contract_enforcement():
    result = ScraperResult(
        listings=[
            {
                "external_id": "1",
                "url": "notaurl",
                "title": " ",
                "images": ["https://img.example/1.jpg", "https://img.example/1.jpg"],
            }
        ],
        metrics=PipelineMetrics(source="olx"),
    )
    ads, meta = adapt_v2("olx", result)
    assert len(ads) == 1
    assert ("invalid_url" in ads[0].quality_flags) or ("missing_url" in ads[0].quality_flags)
    assert "empty_title" in ads[0].quality_flags
    assert "duplicate_images" in ads[0].quality_flags
    assert meta.reason_buckets["quality_critical"] >= 1
