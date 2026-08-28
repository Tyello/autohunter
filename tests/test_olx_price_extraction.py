from __future__ import annotations

from decimal import Decimal
from pathlib import Path

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
