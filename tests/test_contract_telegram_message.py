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


def test_telegram_message_contract_basic_formatting():
    """Contract: mensagem sempre tem título e preço; URL fica no botão.

    O conteúdo pode evoluir (ex.: Ano, Score, FIPE), mas:
    - 1ª linha: título limpo
    - Deve existir linha "Preço: ..."
    - Deve existir linha "Score: N/100"
    - Não deve conter URL no corpo
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

    text = _build_text(listing)
    lines = text.splitlines()

    assert lines[0] == "Honda Civic Hatch 1994"
    assert "Preço: R$ 32.000,00" in lines
    assert any(l.startswith("Score: ") and l.endswith("/100") for l in lines)
    # URL não deve aparecer no corpo da mensagem
    assert all("http" not in line for line in lines)


def test_telegram_message_contract_ml_tracking_is_canonical():
    """Contract: URLs de tracking do ML nunca vão no corpo do Telegram."""
    from app.bot.sender import _build_text

    listing = _Listing(
        source="mercadolivre",
        external_id="MLB6177621992",
        title="Honda Civic 2015 2.0 LXR 16V",
        price=77990.0,
        location=None,
        url=(
            "https://click1.mercadolivre.com.br/mclics/clicks/external?foo=bar&baz=qux"
        ),
    )

    text = _build_text(listing)
    # URL de tracking não deve aparecer na mensagem
    assert "click1.mercadolivre.com.br" not in text
    assert "http" not in text
