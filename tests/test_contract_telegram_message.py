from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Listing:
    source: str
    external_id: str
    title: str
    price: float | None
    location: str | None = None
    url: str | None = None
    thumbnail_url: str | None = None


@dataclass
class _Notification:
    score_v2: int
    score_breakdown: dict


def test_telegram_message_contract_vnext_formatting():
    """Contract (vNext): decisão em 3s.

    - 1ª linha: score + título (sem URL)
    - Deve existir preço (ou 'Preço: —')
    - Deve existir fonte
    - Não deve conter URL no corpo (URL fica no botão)
    """
    from app.bot.sender import _build_text

    listing = _Listing(
        source="chavesnamao",
        external_id="",
        title="Honda Civic Hatch 1994   ",
        price=32000.0,
        location="Curitiba, PR",
        url="https://www.exemplo.com/anuncio?id=123&utm_source=ads#fragment",
    )

    n = _Notification(
        score_v2=82,
        score_breakdown={
            "total": 82,
            "reasons": ["Preço competitivo", "Match forte com sua wishlist"],
        },
    )

    text = _build_text(listing, notification=n)
    lines = text.splitlines()

    assert lines[0].startswith("🔥 82/100 — Honda Civic Hatch 1994")
    assert any("R$ 32.000,00" in l for l in lines)
    assert any("Fonte: chavesnamao" in l for l in lines)

    # URL não deve aparecer no corpo da mensagem
    assert all("http" not in line for line in lines)


def test_telegram_message_contract_ml_tracking_not_in_body():
    """Contract: URLs de tracking do ML nunca vão no corpo do Telegram."""
    from app.bot.sender import _build_text

    listing = _Listing(
        source="mercadolivre",
        external_id="MLB6177621992",
        title="Honda Civic 2015 2.0 LXR 16V",
        price=77990.0,
        location=None,
        url="https://click1.mercadolivre.com.br/mclics/clicks/external?foo=bar&baz=qux",
    )

    n = _Notification(score_v2=70, score_breakdown={"total": 70, "reasons": []})

    text = _build_text(listing, notification=n)
    assert "click1.mercadolivre.com.br" not in text
    assert "http" not in text
