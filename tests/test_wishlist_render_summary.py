from app.bot.renderers import render_user_wishlists
from types import SimpleNamespace
from app.bot.renderers import render_wishlist_filters


def test_render_user_wishlists_empty_keeps_guidance():
    text = render_user_wishlists([])
    assert "Você ainda não criou nenhuma busca." in text
    assert "Crie uma busca" in text


def test_render_user_wishlists_summary_counts_filters_and_tracked():
    text = render_user_wishlists([
        {"index": 1, "query": "civic si", "filters_count": 0, "filters": [], "tracked_count": 0, "tracked_limit": 3, "is_active": True, "include_auctions": True},
        {"index": 2, "query": "miata", "filters_count": 2, "filters": [{"field": "year", "operator": "gte", "value": "2017"}, {"field": "year", "operator": "lte", "value": "2021"}], "tracked_count": 1, "tracked_limit": 3, "is_active": True, "include_auctions": False},
    ])
    assert "🎯 Minhas buscas" in text
    assert "✅ 1. civic si • sem filtros" in text
    assert "✅ 2. miata • 1 filtro • 1 rastreado" in text
    assert "Escolha uma busca para gerenciar:" in text


def test_render_user_wishlists_summary_shows_notifications_24h_count():
    text = render_user_wishlists([
        {"index": 1, "query": "civic si", "filters_count": 0, "filters": [], "tracked_count": 0, "tracked_limit": 3, "notifications_24h_count": 3, "is_active": True, "include_auctions": True},
    ])
    assert "3 alertas hoje" in text


def test_render_user_wishlists_summary_limits_filters():
    text = render_user_wishlists([
        {"index": 1, "query": "civic hatch", "filters": [
            {"field": "year", "operator": "gte", "value": "2017"},
            {"field": "year", "operator": "lte", "value": "2021"},
            {"field": "price", "operator": "lte", "value": "150000"},
            {"field": "city", "operator": "eq", "value": "São Paulo"},
            {"field": "state", "operator": "eq", "value": "SP"},
        ], "tracked_count": 0, "tracked_limit": 3, "is_active": True, "include_auctions": True},
    ])
    assert "4 filtros" in text


def test_render_user_wishlists_legacy_numeric_values_are_tolerant():
    text = render_user_wishlists([
        {"index": 1, "query": "legacy", "filters": [
            {"field": "price", "operator": "lte", "value": "até 150.000"},
            {"field": "mileage_km", "operator": "lte", "value": "90.000 km"},
            {"field": "year", "operator": "gte", "value": "abc"},
        ], "tracked_count": 0, "tracked_limit": 3},
    ])
    assert "3 filtros" in text


def test_render_user_wishlists_mixed_valid_invalid_filters_do_not_break():
    text = render_user_wishlists([
        {"index": 1, "query": "mixed", "filters": [
            {"field": "year", "operator": "gte", "value": "2017"},
            {"field": "year", "operator": "lte", "value": "abc"},
            {"field": "city", "operator": "eq", "value": "São Paulo"},
        ], "tracked_count": 0, "tracked_limit": 3},
    ])
    assert "2 filtros" in text


def test_render_user_wishlists_single_year_range_is_friendly():
    text = render_user_wishlists([
        {"index": 1, "query": "a4 avant", "filters": [
            {"field": "year", "operator": "gte", "value": "2019"},
            {"field": "year", "operator": "lte", "value": "2019"},
        ], "tracked_count": 0, "tracked_limit": 3, "is_active": True, "include_auctions": True},
    ])
    assert "1 filtro" in text


def test_render_wishlist_filters_single_year_range_is_friendly():
    filters = [
        SimpleNamespace(field="year", operator="gte", value="2019"),
        SimpleNamespace(field="year", operator="lte", value="2019"),
    ]
    text = render_wishlist_filters(filters, wishlist_query="a4 avant")
    assert "1. Ano 2019" in text
    assert "Ano entre 2019 e 2019" not in text


def test_render_user_wishlists_legacy_format_still_supported():
    class _WL:
        query = "legacy"

    text = render_user_wishlists([_WL()])
    assert text.startswith("Minhas buscas:")
    assert "1. legacy" in text


def test_render_user_wishlists_filters_accept_object_shape():
    text = render_user_wishlists([
        {"index": 1, "query": "obj", "filters": [
            SimpleNamespace(field="year", operator="gte", value="2018"),
            SimpleNamespace(field="year", operator="lte", value="2020"),
            SimpleNamespace(field="state", operator="eq", value="SP"),
            SimpleNamespace(value="broken"),
        ], "tracked_count": 0, "tracked_limit": 3, "is_active": True, "include_auctions": True},
    ])
    assert "2 filtros" in text


def test_render_user_wishlists_filters_mixed_dict_and_object():
    text = render_user_wishlists([
        {"index": 1, "query": "mixed", "filters": [
            {"field": "year", "operator": "gte", "value": "2018"},
            SimpleNamespace(field="year", operator="lte", value="2020"),
        ], "tracked_count": 0, "tracked_limit": 3, "is_active": True, "include_auctions": True},
    ])
    assert "1 filtro" in text
