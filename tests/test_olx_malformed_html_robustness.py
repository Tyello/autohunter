from __future__ import annotations

"""Valida que a troca html.parser -> lxml em app/scrapers/olx.py (spike
docs/spikes/scrapling-parser-spike.md) nao introduziu risco de excecao nao
tratada diante de HTML malformado/truncado.

Motivacao: html.parser (stdlib) e notoriamente tolerante a markup quebrado.
lxml e mais estrito por padrao, mas a libxml2 (usada por baixo do BeautifulSoup
"lxml") roda em modo de recuperacao (recover=True) por padrao no parser HTML
de bs4 -- a duvida real e se ha algum input adversario plausivel em producao
(resposta de rede truncada, encoding quebrado, bytes nulos, HTML profundamente
aninhado) que faz lxml levantar excecao onde html.parser silenciosamente
tolerava. Testado nos 3 pontos de app/scrapers/olx.py que hoje usam lxml:
_extract_olx_detail_thumbnail (252), _extract_next_data_json (358),
_fallback_parse_from_cards (757).
"""

from bs4 import BeautifulSoup

from app.scrapers.olx import (
    _extract_next_data_json,
    _extract_olx_detail_thumbnail,
    _fallback_parse_from_cards,
)

MALFORMED_INPUTS = {
    "truncated_mid_tag": (
        '<html><head><meta property="og:image" content="https://img.olx.com.br/x'
    ),
    "unclosed_nested_divs": "<div>" * 5000 + "<p>conteudo</p>",
    "null_bytes_embedded": (
        '<html><body><meta property="og:image" content="https://img.olx.com.br/x.jpg">'
        "\x00\x00\x00<div>resto</div></body></html>"
    ),
    "broken_attribute_quoting": (
        '<html><body><a data-testid=adcard-link href=https://olx.com.br/item-123456>titulo '
        '<span class=olx-adcard__price>R$ 1.000</span></a></body></html>'
    ),
    "stray_angle_brackets_in_text": (
        '<html><body><a data-testid="adcard-link" href="https://olx.com.br/item-654321">'
        "Carro 4x4 < 50 mil km > ótimo estado</a></body></html>"
    ),
    "empty_string": "",
    "not_html_binary_garbage": "\xff\xfe\x00\x01\x02random binary noise not html at all\x00",
    "truncated_next_data_json": (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        '{"props": {"pageProps": {"ads": [{"listId": 123456, "subject": "trunc'
    ),
    "mismatched_closing_tags": (
        "<html><body><div><span><a data-testid=\"adcard-link\" "
        'href="https://olx.com.br/item-987654">titulo</span></a></div>'
        '<span class="olx-adcard__price">R$ 500</p></body></html>'
    ),
}


def test_extract_olx_detail_thumbnail_never_raises_on_malformed_html():
    for name, html in MALFORMED_INPUTS.items():
        try:
            _extract_olx_detail_thumbnail(html, "https://www.olx.com.br/item")
        except Exception as exc:  # pragma: no cover - falha aqui e o ponto do teste
            raise AssertionError(f"_extract_olx_detail_thumbnail lancou excecao para caso {name!r}: {exc!r}") from exc


def test_extract_next_data_json_never_raises_on_malformed_html():
    for name, html in MALFORMED_INPUTS.items():
        try:
            _extract_next_data_json(html)
        except Exception as exc:  # pragma: no cover - falha aqui e o ponto do teste
            raise AssertionError(f"_extract_next_data_json lancou excecao para caso {name!r}: {exc!r}") from exc


def test_fallback_parse_from_cards_never_raises_on_malformed_html():
    for name, html in MALFORMED_INPUTS.items():
        try:
            _fallback_parse_from_cards(html)
        except Exception as exc:  # pragma: no cover - falha aqui e o ponto do teste
            raise AssertionError(f"_fallback_parse_from_cards lancou excecao para caso {name!r}: {exc!r}") from exc


def test_fallback_parse_from_cards_still_extracts_from_broken_but_recoverable_markup():
    """Litmus nao-raso: nao basta nao-lancar excecao, precisa continuar
    extraindo o card quando o HTML e recuperavel (tags mal fechadas mas com
    a estrutura ainda reconhecivel), provando que lxml em modo recover nao
    silenciosamente descarta dados que html.parser recuperaria."""
    html = MALFORMED_INPUTS["broken_attribute_quoting"]
    items = _fallback_parse_from_cards(html)
    assert len(items) == 1
    assert items[0].external_id == "123456"
    assert items[0].price is not None

    html_mismatched = MALFORMED_INPUTS["mismatched_closing_tags"]
    items_mismatched = _fallback_parse_from_cards(html_mismatched)
    assert len(items_mismatched) == 1
    assert items_mismatched[0].external_id == "987654"


def test_lxml_and_html_parser_agree_on_crash_safety_for_all_malformed_inputs():
    """Compara diretamente as duas variantes de parser (nao so as funcoes do
    scraper) para isolar se uma eventual divergencia vem do parser em si."""
    for name, html in MALFORMED_INPUTS.items():
        try:
            BeautifulSoup(html, "html.parser")
        except Exception as exc:  # pragma: no cover
            raise AssertionError(f"html.parser (baseline) lancou excecao para {name!r}: {exc!r}") from exc
        try:
            BeautifulSoup(html, "lxml")
        except Exception as exc:  # pragma: no cover
            raise AssertionError(f"lxml lancou excecao para {name!r} onde html.parser nao lancou: {exc!r}") from exc
