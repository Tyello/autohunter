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
    """Contract: mensagem sempre tem título, preço e URL normalizada.

    O conteúdo pode evoluir (ex.: Ano, Score, FIPE), mas:
    - 1ª linha: título limpo
    - Deve existir linha "Preço: ..."
    - Deve existir linha "Score: N/100"
    - A última linha deve ser uma URL sem query/fragment
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
    # URL sempre sem query/fragment
    assert lines[-1] == "https://www.exemplo.com/anuncio"


def test_telegram_message_contract_ml_tracking_is_canonical():
    """Contract: ML tracking URLs nunca vão pro Telegram (vira URL canônica curta)."""
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
    # a última linha deve ser a URL estável, sem tracking
    assert text.splitlines()[-1] == "https://carro.mercadolivre.com.br/MLB-6177621992-_JM"