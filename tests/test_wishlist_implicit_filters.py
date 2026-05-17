from app.services.wishlists_service import parse_wishlist_query_with_implicit_filters


def _pairs(parsed):
    return [(f.field, f.operator, f.value) for f in parsed.filters]


def test_ate_20000_is_price_not_year():
    parsed = parse_wishlist_query_with_implicit_filters("touareg até 20000")
    assert parsed.cleaned_query == "touareg"
    assert _pairs(parsed) == [("price", "lte", "20000")]


def test_ate_15000_is_price_and_no_residual_zero():
    parsed = parse_wishlist_query_with_implicit_filters("touareg até 15000")
    assert parsed.cleaned_query == "touareg"
    assert "0" not in parsed.cleaned_query
    assert _pairs(parsed) == [("price", "lte", "15000")]


def test_ate_20k_and_brl_formats_are_price():
    parsed_k = parse_wishlist_query_with_implicit_filters("touareg até 20k")
    assert parsed_k.cleaned_query == "touareg"
    assert _pairs(parsed_k) == [("price", "lte", "20000")]

    parsed_brl = parse_wishlist_query_with_implicit_filters("corolla até R$ 120.000")
    assert parsed_brl.cleaned_query == "corolla"
    assert _pairs(parsed_brl) == [("price", "lte", "120000")]


def test_ate_2000_is_year():
    parsed = parse_wishlist_query_with_implicit_filters("touareg até 2000")
    assert parsed.cleaned_query == "touareg"
    assert _pairs(parsed) == [("year", "lte", "2000")]


def test_year_and_price_ranges_keep_distinction():
    year_range = parse_wishlist_query_with_implicit_filters("audi a5 entre 2017 e 2021")
    assert year_range.cleaned_query == "audi a5"
    assert _pairs(year_range) == [("year", "gte", "2017"), ("year", "lte", "2021")]

    price_range = parse_wishlist_query_with_implicit_filters("audi a5 entre 90000 e 130000")
    assert price_range.cleaned_query == "audi a5"
    assert _pairs(price_range) == [("price", "gte", "90000"), ("price", "lte", "130000")]
