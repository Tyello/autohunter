from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from bs4 import BeautifulSoup

from app.scrapers.olx import (
    _extract_items_from_next_data,
    _extract_next_data_json,
    _extract_rsc_json_chunks,
    _fallback_parse_from_cards,
    _parse_olx_listing_items,
)


def test_real_fixture_search_rsc_extracts_price():
    """OLX migrou as paginas de busca do Pages Router (<script id="__NEXT_DATA__">)
    para o streaming RSC do App Router (self.__next_f.push([1, "..."])). O parser
    antigo so olhava para __NEXT_DATA__, entao passou a nao achar nenhum item nessas
    paginas e caia no fallback de cards em HTML, cujo seletor de preco
    (.olx-adcard__price) tambem estava desatualizado -- titulo/url eram extraidos
    mas o preco vinha sempre None (ex.: Honda Fit EX/S 1.5 2007, listId 1530131166).

    Este fixture contem um trecho real (nao sintetico) de um push RSC capturado de
    uma pagina de busca real da OLX, com dois anuncios reais (Honda Fit 2021 e 2005).
    """
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "search_rsc_price_nodes.html"
    html = fixture_path.read_text(encoding="utf-8")

    # Confirma a premissa do bug: nao ha __NEXT_DATA__ nesse formato de pagina.
    assert _extract_next_data_json(html) is None

    items = _parse_olx_listing_items(html)
    by_id = {it.external_id: it for it in items}

    assert by_id["1503037487"].price == Decimal("69900")
    assert by_id["1512208902"].price == Decimal("32800")


def test_rsc_json_chunks_are_extracted_and_walked():
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "search_rsc_price_nodes.html"
    html = fixture_path.read_text(encoding="utf-8")

    chunks = _extract_rsc_json_chunks(html)
    assert chunks

    items = _extract_items_from_next_data(chunks)
    ids = {it.external_id for it in items}
    assert {"1503037487", "1512208902"} <= ids


def test_fallback_card_parser_alone_finds_nothing_on_rsc_markup():
    """Documenta por que confiar so no fallback de cards nao resolve o caso real:
    a pagina RSC atual nao tem os elementos `a[data-testid="adcard-link"]` /
    `.olx-adcard__price` que esse fallback espera (o layout mudou de estrutura de
    DOM para dados servidos via streaming RSC). E por isso que
    _parse_olx_listing_items precisa tentar a extracao RSC antes de cair no
    fallback de cards."""
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "search_rsc_price_nodes.html"
    html = fixture_path.read_text(encoding="utf-8")

    items = _fallback_parse_from_cards(html)
    assert items == []


def test_fallback_card_parser_extracts_real_cards():
    """Fecha a lacuna documentada na spike (docs/spikes/scrapling-parser-spike.md
    secao 3): _fallback_parse_from_cards (app/scrapers/olx.py:757) nunca tinha
    sido exercitado com HTML de card positivo (data-testid="adcard-link" +
    .olx-adcard__price), so com fixtures RSC/detalhe onde ele retorna [].

    A fixture usa os mesmos dois anuncios reais (titulo/preco/listId/imagem)
    ja commitados em search_rsc_price_nodes.html, com a casca de DOM
    reconstruida para casar com os seletores que o fallback usa (ver
    docstring da propria fixture)."""
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "search_cards_fallback.html"
    html = fixture_path.read_text(encoding="utf-8")

    items = _fallback_parse_from_cards(html)
    by_id = {it.external_id: it for it in items}

    assert set(by_id) == {"1503037487", "1512208902"}

    fit_2021 = by_id["1503037487"]
    assert fit_2021.title == "Honda Fit Ex/s/ex 1.5 Flex/flexone 16V 5P Aut. 2021"
    assert fit_2021.price == Decimal("69900")
    assert fit_2021.url.endswith("1503037487")
    assert fit_2021.thumbnail_url == "https://img.olx.com.br/images/73/730626405997082.webp"

    fit_2005 = by_id["1512208902"]
    assert fit_2005.title == "Honda Fit LXL 1.4/ 1.4 8v/16v 2005"
    assert fit_2005.price == Decimal("32800")
    assert fit_2005.url.endswith("1512208902")
    assert fit_2005.thumbnail_url == "https://img.olx.com.br/images/27/278617417194654.jpg"


def test_fallback_card_parser_html_parser_vs_lxml_equivalence():
    """Prova a equivalencia semantica entre BS4 html.parser e lxml no caminho
    de fallback de cards antes de trocar o parser (mesma cautela do ADR-0001
    aplicada aos outros 2 pontos de app/scrapers/olx.py na spike)."""
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "search_cards_fallback.html"
    html = fixture_path.read_text(encoding="utf-8")

    def _extract(parser: str) -> list[tuple[str, str, str, object, str | None]]:
        soup = BeautifulSoup(html, parser)
        out = []
        for a in soup.select('a[data-testid="adcard-link"]'):
            href = a.get("href")
            title = (a.get_text(" ", strip=True) or "").strip()
            container = a.find_parent()
            price_el = container.select_one(".olx-adcard__price") if container else None
            price_text = price_el.get_text(strip=True) if price_el else None
            out.append((href, title, price_text))
        return out

    assert _extract("html.parser") == _extract("lxml")
    assert _extract("html.parser") == [
        (
            "https://pb.olx.com.br/paraiba/autos-e-pecas/carros-vans-e-utilitarios/honda-fit-ex-s-ex-1-5-flex-flexone-16v-5p-aut-2021-1503037487",
            "Honda Fit Ex/s/ex 1.5 Flex/flexone 16V 5P Aut. 2021",
            "R$ 69.900",
        ),
        (
            "https://sp.olx.com.br/sao-paulo-e-regiao/autos-e-pecas/carros-vans-e-utilitarios/honda-fit-lxl-1-4-1-4-flex-8v-16v-5p-mec-2005-1512208902",
            "Honda Fit LXL 1.4/ 1.4 8v/16v 2005",
            "R$ 32.800",
        ),
    ]
