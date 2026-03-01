from app.scrapers.dual_run import compare_results
from app.scrapers.source_contract import NormalizedAd, ResultMetadata, SourceResult, normalize_raw_items
from app.services.source_configs_service import get_source_impl_flags


def test_normalize_raw_items_contract_validation():
    raw = [
        {"source": "olx", "external_id": "1", "url": "https://www.olx.com.br/a?utm=1", "title": "  Civic  "},
        {"source": "olx", "external_id": "1", "url": "https://www.olx.com.br/a", "price": 10},
    ]
    ads = normalize_raw_items("olx", raw)
    assert len(ads) == 1
    ad = ads[0]
    assert isinstance(ad, NormalizedAd)
    assert ad.currency == "BRL"
    assert ad.url == "https://www.olx.com.br/a"


def test_compare_results_counts_and_field_diffs():
    v1 = SourceResult(
        ads=[
            NormalizedAd(source="olx", external_id="1", url="u1", title="A", price=100),
            NormalizedAd(source="olx", external_id="2", url="u2", title="B", price=200),
        ],
        metadata=ResultMetadata(source="olx", impl="v1", duration_ms=1, raw_count=2, normalized_count=2),
    )
    v2 = SourceResult(
        ads=[
            NormalizedAd(source="olx", external_id="1", url="u1", title="A*", price=100),
            NormalizedAd(source="olx", external_id="3", url="u3", title="C", price=300),
        ],
        metadata=ResultMetadata(source="olx", impl="v2", duration_ms=1, raw_count=2, normalized_count=2),
    )

    comp = compare_results(v1, v2)
    assert comp["v1_count"] == 2
    assert comp["v2_count"] == 2
    assert comp["intersection"] == 1
    assert comp["only_v1_count"] == 1
    assert comp["only_v2_count"] == 1
    assert comp["field_diffs"][0]["external_id"] == "1"


def test_impl_flags_from_source_extra():
    impl, dual_mode = get_source_impl_flags({"impl": "dual", "dual_mode": "v2_primary"})
    assert impl == "dual"
    assert dual_mode == "v2_primary"

    impl2, dual_mode2 = get_source_impl_flags({"impl": "invalid", "dual_mode": "??"})
    assert impl2 == "v1"
    assert dual_mode2 == "v1_primary"
