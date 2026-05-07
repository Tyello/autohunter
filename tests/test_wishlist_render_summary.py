from app.bot.renderers import render_user_wishlists


def test_render_user_wishlists_empty_keeps_guidance():
    text = render_user_wishlists([])
    assert "Você não tem wishlists." in text
    assert "/wishlist_add" in text


def test_render_user_wishlists_summary_counts_filters_and_tracked():
    text = render_user_wishlists([
        {"index": 1, "query": "civic si", "filters_count": 0, "tracked_count": 0, "tracked_limit": 3, "is_active": True},
        {"index": 2, "query": "miata", "filters_count": 2, "tracked_count": 1, "tracked_limit": 3, "is_active": True},
    ])
    assert "🎯 Suas wishlists" in text
    assert "1. civic si" in text
    assert "Filtros: 0" in text
    assert "Rastreados: 0/3" in text
    assert "Notificações: 0 nas últimas 24h" in text
    assert "2. miata" in text
    assert "Filtros: 2" in text
    assert "Rastreados: 1/3" in text
    assert "Notificações: 0 nas últimas 24h" in text
    assert "Status:" not in text
    assert "Escolha uma ação:" in text


def test_render_user_wishlists_summary_shows_notifications_24h_count():
    text = render_user_wishlists([
        {"index": 1, "query": "civic si", "filters_count": 0, "tracked_count": 0, "tracked_limit": 3, "notifications_24h_count": 3, "is_active": True},
    ])
    assert "Notificações: 3 nas últimas 24h" in text


def test_render_user_wishlists_legacy_format_still_supported():
    class _WL:
        query = "legacy"

    text = render_user_wishlists([_WL()])
    assert text.startswith("Wishlists:")
    assert "1. legacy" in text
