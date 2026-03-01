from app.sources.adapters.v1 import adapt_v1
from app.sources.compare import compare_ads
from app.sources.flags import read_source_impl_flags


def test_normalize_raw_items_contract_validation():
    ads, _ = adapt_v1(
        "olx",
        [
            {"source": "olx", "external_id": "1", "url": "https://www.olx.com.br/a?utm=1", "title": "  Civic  "},
            {"source": "olx", "external_id": "1", "url": "https://www.olx.com.br/a", "price": 10},
        ],
    )
    assert len(ads) == 2
    assert ads[0].currency == "BRL"
    assert ads[0].url == "https://www.olx.com.br/a?utm=1"


def test_compare_results_counts_and_field_diffs():
    v1, _ = adapt_v1("olx", [{"external_id": "1", "url": "u1", "title": "A", "price": 100}, {"external_id": "2", "url": "u2", "title": "B", "price": 200}])
    v2, _ = adapt_v1("olx", [{"external_id": "1", "url": "u1", "title": "A*", "price": 100}, {"external_id": "3", "url": "u3", "title": "C", "price": 300}])

    comp = compare_ads(v1, v2)
    assert comp["matched"] == 1
    assert comp["misses_v2"] == 1
    assert comp["extras_v2"] == 1


def test_impl_flags_from_source_extra():
    flags = read_source_impl_flags({"impl": "dual", "dual_mode": "compare_and_use_v2"})
    assert flags.impl == "dual"
    assert flags.dual_mode == "compare_and_use_v2"

    flags2 = read_source_impl_flags({"impl": "invalid", "dual_mode": "??"})
    assert flags2.impl == "v1"
    assert flags2.dual_mode == "compare_only"
