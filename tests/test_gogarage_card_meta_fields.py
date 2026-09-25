from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.scrapers.gogarage import scrape_gogarage
from app.sources.types import ScrapeContext


def _fixture_html() -> str:
    path = Path(__file__).parent / "fixtures" / "gogarage" / "search_cards.html"
    return path.read_text(encoding="utf-8")


def test_year_km_location_read_from_card_meta_without_detail_fetch():
    """GoGarage embute ano/km/localizacao no HTML server-renderizado dos cards de busca
    (spans '.bc-meta-item' com icones bi-calendar3/bi-speedometer2/bi-geo-alt) --
    confirmado em sondagem ao vivo (tests/fixtures/gogarage/search_cards.html, captura
    real trimada). Isso deve evitar gastar orcamento de fetch_details so por causa do
    ano/km, que antes nunca eram extraidos."""
    html = _fixture_html()
    ctx = ScrapeContext(source="gogarage")

    with patch("app.scrapers.gogarage.fetch_html", return_value=html), patch(
        "app.scrapers.gogarage.fetch_details"
    ) as mock_details:
        items = scrape_gogarage("https://www.gogarage.com.br/index.php?q=carro", ctx)

    assert mock_details.called is False

    by_id = {it["external_id"]: it for it in items}

    compass = by_id["jeep-compass-2020-2020"]
    assert compass["year"] == 2020
    assert compass["km"] == 54600
    assert compass["location"] == "Erechim/RS"
    assert int(compass["price"]) == 103000

    palio = by_id["fiat-palio-essence-1-6-2015"]
    assert palio["year"] == 2015
    assert palio["km"] == 160000
    assert palio["location"] == "Arroio do Meio/RS"

    santana = by_id["santana-glsi-1993-branco-perola"]
    assert santana["year"] == 1993
    assert santana["km"] == 247000
    assert santana["location"] == "Santo André/SP"
