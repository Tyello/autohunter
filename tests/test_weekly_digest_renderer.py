from app.bot.weekly_digest_renderer import render_weekly_digest, render_weekly_digest_candidates


def test_renderer_empty():
    text = render_weekly_digest({"days": 7, "totals": {"sent": 0}})
    assert "Nenhum alerta enviado" in text
    assert "/wishlist" in text and "/buscar" in text


def test_renderer_with_items_and_limits_and_truncate():
    payload = {
        "days": 7,
        "totals": {"sent": 8, "wishlists_with_results": 4, "price_drops": 3},
        "by_source": [{"source": "olx", "count": 5}, {"source": "mercado_livre", "count": 3}],
        "by_wishlist": [{"wishlist": "Civic Si", "count": 8}],
        "top_opportunities": [
            {"title": "X" * 120, "score_v2": 88, "price": 123000, "source": "olx", "wishlist": "Civic", "mileage_km": 82000, "state": "SP", "year": 2015, "rarity_context": {"is_rare": True, "label": "raro"}},
            *[{"title": f"Carro {i}", "score_v2": 80, "price": 100000, "source": "olx", "wishlist": "W", "mileage_km": None, "location": None} for i in range(10)],
        ],
        "rare_opportunities": [{"title": f"Raro {i}", "score_v2": 80, "price": 118000, "state": "SP", "wishlist": "Civic Si", "rarity_context": {"is_rare": True, "label": "raro"}} for i in range(10)],
        "price_drops": [{"title": f"Drop {i}", "price": 145000} for i in range(10)],
    }
    text = render_weekly_digest(payload)
    assert "🏁 Top oportunidades" in text
    assert "🧬 Achados raros" in text
    assert "📉 Quedas de preço" in text
    assert "🔎 Buscas com mais alertas" in text
    assert "R$ 123.000" in text
    assert "82.000 km" in text
    assert "SP" in text
    assert "Busca: Civic" in text
    assert "Fonte: OLX" in text
    assert text.count("\n1.") == 1
    assert text.count(" caiu para ") == 3
    assert "…" in text


def test_renderer_with_missing_fields_does_not_break():
    payload = {
        "days": 7,
        "totals": {"sent": 1, "wishlists_with_results": 1, "price_drops": 0},
        "top_opportunities": [{"title": "Sem dados", "score_v2": None, "price": None, "source": None, "wishlist": None, "mileage_km": None, "location": None}],
    }
    text = render_weekly_digest(payload)
    assert "Preço indisponível" in text
    assert "km indisponível" in text
    assert "local indisponível" in text
    assert "score -" in text


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


def test_renderer_hides_rare_block_when_no_reliable_rarity():
    payload = {"days": 7, "totals": {"sent": 1, "wishlists_with_results": 1, "price_drops": 0}, "top_opportunities": [{"title": "A", "score_v2": 70, "price": 90000, "wishlist": "Civic"}]}
    text = render_weekly_digest(payload)
    assert "🧬 Achados raros" not in text
