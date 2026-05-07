from app.bot.renderers import render_user_wishlists


def test_render_user_wishlists_empty_keeps_guidance():
    text = render_user_wishlists([])
    assert "Você ainda não criou nenhuma busca." in text
    assert "Crie uma busca" in text


def test_render_user_wishlists_summary_counts_filters_and_tracked():
    text = render_user_wishlists([
        {"index": 1, "query": "civic si", "filters_count": 0, "filters": [], "tracked_count": 0, "tracked_limit": 3, "is_active": True},
        {"index": 2, "query": "miata", "filters_count": 2, "filters": [{"field": "year", "operator": "gte", "value": "2017"}, {"field": "year", "operator": "lte", "value": "2021"}], "tracked_count": 1, "tracked_limit": 3, "is_active": True},
    ])
    assert "🎯 Minhas buscas" in text
    assert "1. civic si" in text
    assert "Filtros:\n- Nenhum filtro" in text
    assert "Anúncios rastreados: 0/3" in text
    assert "Alertas enviados hoje: 0" in text
    assert "2. miata" in text
    assert "Filtros:\n- Ano entre 2017 e 2021" in text
    assert "Anúncios rastreados: 1/3" in text
    assert "Alertas enviados hoje: 0" in text
    assert "Status:" not in text
    assert "Escolha uma ação:" in text


def test_render_user_wishlists_summary_shows_notifications_24h_count():
    text = render_user_wishlists([
        {"index": 1, "query": "civic si", "filters_count": 0, "filters": [], "tracked_count": 0, "tracked_limit": 3, "notifications_24h_count": 3, "is_active": True},
    ])
    assert "Alertas enviados hoje: 3" in text


def test_render_user_wishlists_summary_limits_filters():
    text = render_user_wishlists([
        {"index": 1, "query": "civic hatch", "filters": [
            {"field": "year", "operator": "gte", "value": "2017"},
            {"field": "year", "operator": "lte", "value": "2021"},
            {"field": "price", "operator": "lte", "value": "150000"},
            {"field": "city", "operator": "eq", "value": "São Paulo"},
            {"field": "state", "operator": "eq", "value": "SP"},
        ], "tracked_count": 0, "tracked_limit": 3, "is_active": True},
    ])
    assert "Ano entre 2017 e 2021" in text
    assert "Preço até R$ 150.000" in text
    assert "+1 filtros" in text


def test_render_user_wishlists_legacy_numeric_values_are_tolerant():
    text = render_user_wishlists([
        {"index": 1, "query": "legacy", "filters": [
            {"field": "price", "operator": "lte", "value": "até 150.000"},
            {"field": "mileage_km", "operator": "lte", "value": "90.000 km"},
            {"field": "year", "operator": "gte", "value": "abc"},
        ], "tracked_count": 0, "tracked_limit": 3},
    ])
    assert "Preço até R$ 150.000" in text
    assert "KM até 90.000" in text
    assert "year gte abc" in text


def test_render_user_wishlists_mixed_valid_invalid_filters_do_not_break():
    text = render_user_wishlists([
        {"index": 1, "query": "mixed", "filters": [
            {"field": "year", "operator": "gte", "value": "2017"},
            {"field": "year", "operator": "lte", "value": "abc"},
            {"field": "city", "operator": "eq", "value": "São Paulo"},
        ], "tracked_count": 0, "tracked_limit": 3},
    ])
    assert "Ano a partir de 2017" in text
    assert "Cidade: São Paulo" in text


def test_render_user_wishlists_legacy_format_still_supported():
    class _WL:
        query = "legacy"

    text = render_user_wishlists([_WL()])
    assert text.startswith("Minhas buscas:")
    assert "1. legacy" in text
