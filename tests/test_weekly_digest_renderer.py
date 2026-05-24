from app.bot.weekly_digest_renderer import render_weekly_digest


def test_renderer_empty():
    text = render_weekly_digest({"days": 7, "totals": {"sent": 0}})
    assert "Sem alertas enviados" in text


def test_renderer_with_items_and_limits_and_truncate():
    payload = {
        "days": 7,
        "totals": {"sent": 2, "wishlists_with_results": 1, "price_drops": 1},
        "top_opportunities": [
            {"title": "X" * 120, "score_v2": 88, "price": 123000, "source": "olx", "wishlist": "Civic"},
        ],
        "price_drops": [{"title": "Golf GTI 2017", "price": 145000}],
    }
    text = render_weekly_digest(payload)
    assert "Top oportunidades" in text
    assert "Price drops" in text
    assert "…" in text
