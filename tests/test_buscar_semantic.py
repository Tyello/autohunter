import types
from app.bot import handlers


def test_parse_implicit_price_lte_and_state():
    parsed = handlers.parse_wishlist_query_with_implicit_filters("civic si até 120000 sp")
    cleaned, state_filters = handlers._extract_state_filter_from_query(parsed.cleaned_query)
    assert cleaned == "civic si"
    assert any(f.field == "price" and f.operator == "lte" and f.value == "120000" for f in parsed.filters)
    assert any(f.field == "state" and f.operator == "eq" and f.value == "SP" for f in state_filters)


def test_parse_implicit_price_gte():
    cleaned, filters = handlers._extract_extra_price_filters("golf gti acima de 90000")
    assert cleaned == "golf gti"
    assert any(f.field == "price" and f.operator == "gte" and f.value == "90000" for f in filters)


def test_parse_implicit_price_range():
    cleaned, filters = handlers._extract_extra_price_filters("audi a5 entre 90000 e 130000")
    assert cleaned == "audi a5"
    assert any(f.field == "price" and f.operator == "gte" and f.value == "90000" for f in filters)
    assert any(f.field == "price" and f.operator == "lte" and f.value == "130000" for f in filters)


def test_source_selector_kept():
    query, sources = handlers._parse_query_and_sources(["civic", "@mercadolivre"])
    assert query == "civic"
    assert sources == ["mercadolivre"]


def test_listing_semantic_filter_does_not_match_token_ate():
    listing_ok = types.SimpleNamespace(price=119000, location="São Paulo SP", state="SP", year=2020)
    listing_bad = types.SimpleNamespace(price=130000, location="São Paulo SP", state="SP", year=2020)
    filters = [
        types.SimpleNamespace(field="price", operator="lte", value="120000"),
        types.SimpleNamespace(field="state", operator="eq", value="SP"),
    ]
    assert handlers._listing_matches_semantic_filters(listing_ok, filters)
    assert not handlers._listing_matches_semantic_filters(listing_bad, filters)
