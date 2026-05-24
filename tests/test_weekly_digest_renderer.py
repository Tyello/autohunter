from app.bot.weekly_digest_renderer import render_weekly_digest, render_weekly_digest_candidates


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


def test_candidates_renderer_empty():
    text = render_weekly_digest_candidates([], days=7)
    assert "Nenhum usuário com alertas enviados" in text


def test_candidates_renderer_items_and_truncate():
    text = render_weekly_digest_candidates(
        [
            {
                "telegram_chat_id": 123,
                "username": "user",
                "total_sent": 12,
                "total_wishlists_with_results": 3,
                "total_price_drops": 1,
                "top_score_v2": 91,
                "latest_sent_at": "2026-01-01T00:00:00+00:00",
                "sample_wishlist_names": ["x" * 80],
                "sample_listing_titles": ["y" * 90],
            }
        ],
        days=7,
    )
    assert "/admin digest user <chat_id> 7" in text
    assert "📬 Digest semanal — candidatos" in text
    assert "…" in text
