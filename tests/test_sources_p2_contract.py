from app.scrapers.scraper_base.metrics import PipelineMetrics
from app.scrapers.scraper_base.scraper import ScraperResult
from app.sources.adapters.v1 import adapt_v1
from app.sources.adapters.v2 import adapt_v2
from app.sources.compare import compare_ads
from app.sources.flags import read_source_impl_flags
from app.sources.normalize import normalize_ad


def test_normalize_strong_fields_and_quality_flags():
    ad = normalize_ad(
        "olx",
        {
            "external_id": "abc",
            "url": "https://example.com/car?utm_source=x",
            "price": "R$ 45.900",
            "mileage_km": "120.000 km",
            "year": "2018",
            "location": "São Paulo - SP",
        },
    )

    assert ad.source_listing_id == "abc"
    assert ad.url == "https://example.com/car"
    assert ad.price == 45900
    assert ad.km == 120000
    assert ad.year == 2018
    assert ad.city == "São Paulo"
    assert ad.uf == "SP"
    assert "missing_price" not in ad.quality_flags


def test_adapters_never_invent_missing_fields():
    ads, meta = adapt_v1("olx", [{"url": "https://x"}])
    assert meta.impl == "v1"
    assert len(ads) == 1
    assert ads[0].source_listing_id is None
    assert "missing_source_listing_id" in ads[0].quality_flags

    res = ScraperResult(listings=[{"external_id": "1", "url": "https://x/1"}], metrics=PipelineMetrics(source="olx"))
    ads2, meta2 = adapt_v2("olx", res)
    assert meta2.impl == "v2"
    assert ads2[0].source_listing_id == "1"


def test_comparator_matching_and_status():
    v1, _ = adapt_v1("olx", [{"external_id": "1", "url": "https://x/1", "price": 100, "year": 2020, "city": "SP", "uf": "SP"}])
    v2, _ = adapt_v1("olx", [{"external_id": "1", "url": "https://x/1?utm=1", "price": 101, "year": 2020, "city": "SP", "uf": "SP"}])

    report = compare_ads(v1, v2)
    assert report["matched"] == 1
    assert report["overlap"] == 1.0
    assert report["divergences"]["price"] == 1
    assert report["status"] in {"WARN", "FAIL"}


def test_flags_db_driven_modes():
    flags = read_source_impl_flags({"impl": "dual", "dual_mode": "compare_and_use_v2", "compare_cfg": {"min_overlap": 0.9}})
    assert flags.impl == "dual"
    assert flags.dual_mode == "compare_and_use_v2"
    assert flags.compare_cfg["min_overlap"] == 0.9

    defaulted = read_source_impl_flags({"impl": "???", "dual_mode": "??"})
    assert defaulted.impl == "v1"
    assert defaulted.dual_mode == "compare_only"
