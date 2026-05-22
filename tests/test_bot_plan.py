from datetime import datetime, timezone

from app.bot.renderers import _render_usage_bar, render_plan_text


def test_render_usage_bar_simple_cases():
    empty = _render_usage_bar(0, 3)
    assert len(empty) == 10
    assert "█" not in empty

    full = _render_usage_bar(3, 3)
    assert len(full) == 10
    assert full == "█" * 10

    overflow = _render_usage_bar(10, 3)
    assert len(overflow) == 10
    assert overflow == "█" * 10


def test_render_plan_text_free_partial_usage():
    text = render_plan_text(
        plan_code="free",
        premium=False,
        total_wishlists=2,
        max_wishlists=3,
        total_tracked=1,
        max_tracked=3,
        daily_notifications_per_wishlist=5,
    )

    assert "Seu plano: Free" in text
    assert "Buscas salvas" in text
    assert "2/3" in text
    assert "Anúncios rastreados" in text
    assert "1/3" in text
    assert "Até 5 por dia por busca" in text
    assert "█" in text
    assert "░" in text
    assert "/upgrade" in text


def test_render_plan_text_free_limit_reached():
    text = render_plan_text(
        plan_code="free",
        premium=False,
        total_wishlists=3,
        max_wishlists=3,
        total_tracked=3,
        max_tracked=3,
        daily_notifications_per_wishlist=5,
    )

    assert "atingiu o limite de buscas" in text
    assert "atingiu o limite de anúncios rastreados" in text


def test_render_plan_text_premium():
    text = render_plan_text(
        plan_code="premium",
        premium=True,
        total_wishlists=7,
        max_wishlists=15,
        total_tracked=3,
        max_tracked=5,
        daily_notifications_per_wishlist=200,
        current_period_end=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )

    assert "Seu plano: Premium" in text
    assert "7/15" in text
    assert "3/5" in text
    assert "Até 200 por dia por busca" in text
    assert "Válido até" in text
    assert "/upgrade" not in text
