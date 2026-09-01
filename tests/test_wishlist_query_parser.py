from __future__ import annotations

from app.services.wishlist_query_parser import parse_wishlist_query


def test_empty_query_returns_empty_cleaned():
    result = parse_wishlist_query("")
    assert result.cleaned_query == ""
    assert result.year_min is None and result.year_max is None
    assert result.price_min is None and result.price_max is None


def test_no_directives_returns_query_unchanged():
    result = parse_wishlist_query("honda civic si")
    assert result.cleaned_query == "honda civic si"
    assert result.year_min is None and result.year_max is None


def test_year_range_entre_e():
    result = parse_wishlist_query("audi a6 entre 2014 e 2020")
    assert result.year_min == 2014
    assert result.year_max == 2020
    assert "entre" not in result.cleaned_query
    assert "audi a6" in result.cleaned_query


def test_year_range_reversed_order_is_normalized():
    result = parse_wishlist_query("golf entre 2020 e 2014")
    assert result.year_min == 2014
    assert result.year_max == 2020


def test_year_max_ate():
    result = parse_wishlist_query("civic até 2018")
    assert result.year_max == 2018
    assert result.year_min is None


def test_year_min_a_partir_de():
    result = parse_wishlist_query("civic a partir de 2015")
    assert result.year_min == 2015
    assert result.year_max is None


def test_price_range_entre_e_with_k_suffix():
    result = parse_wishlist_query("civic entre 60k e 90k")
    assert result.price_min == 60_000
    assert result.price_max == 90_000


def test_price_max_ate_with_dotted_thousands():
    result = parse_wishlist_query("civic até 90.000")
    assert result.price_max == 90_000


def test_price_min_a_partir_de():
    result = parse_wishlist_query("civic a partir de 50k")
    assert result.price_min == 50_000


def test_year_and_price_directives_combined():
    result = parse_wishlist_query("civic entre 2014 e 2020 entre 60k e 90k")
    assert result.year_min == 2014
    assert result.year_max == 2020
    assert result.price_min == 60_000
    assert result.price_max == 90_000


def test_price_max_ate_does_not_confuse_bare_year():
    result = parse_wishlist_query("civic até 2020")
    assert result.year_max == 2020
    assert result.price_max is None


def test_implausible_price_is_ignored():
    result = parse_wishlist_query("civic entre 1 e 99999999999")
    assert result.price_min is None
    assert result.price_max is None
