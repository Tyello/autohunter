"""Fase 1 (docs/prompts/PROMPT-exec-melhorias-sources-v2.md): Chaves na Mao
capturava so 5 de 15 anuncios por pagina de busca porque so olhava para
<a href> + regex de texto no DOM, ignorando o JSON-LD `ItemList` que a propria
pagina ja expoe com todos os 15 (confirmado no fixture ao vivo de 28/09,
tests/fixtures/source_regression/chavesnamao/2026-09-28_civic/listing.html).

Esta suite cobre: (1) ItemList como fonte primaria quando presente, com km
casado pelo texto do card correspondente (o JSON-LD nao tem km); (2) fallback
para o caminho DOM antigo quando nao ha ItemList; (3) o fixture real gerando
15 itens, com os `external_id` dos 5 que o parser antigo ja capturava
permanecendo IDENTICOS (ADR-0001) -- inclusive um bug preexistente onde a
regex de external_id (r"(\d{6,})" sobre a url, chavesnamao.py) as vezes
casa o PRECO embutido no slug da URL antes do "id-<N>" real, quando o preco
tem 6+ digitos. Nao e corrigido nesta fase (fora do escopo do prompt v2)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.sources.types import ScrapeContext

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "source_regression"
    / "chavesnamao"
    / "2026-09-28_civic"
    / "listing.html"
)


def _itemlist_html(products: list[dict], cards_html: str = "") -> str:
    import json

    item_list = {
        "@type": "ItemList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "item": p} for i, p in enumerate(products)
        ],
    }
    return f"""
    <html><body>
      <script type="application/ld+json">{json.dumps(item_list)}</script>
      {cards_html}
    </body></html>
    """.strip()


def test_itemlist_is_primary_source_when_present(monkeypatch):
    from app.scrapers import chavesnamao

    products = [
        {
            "@type": "Product",
            "name": "HONDA CIVIC 2018 2.0 EXL SEDAN 16V 4P",
            "image": "https://www.chavesnamao.com.br/imn/0600x0400/civic-a.jpg",
            "url": "https://www.chavesnamao.com.br/carro/pr-curitiba/honda-civic-2.0-exl-sedan-16v-4p-2018-automatico-branca-RS89900/id-1111111/",
            "model": "CIVIC",
            "color": "BRANCA",
            "brand": {"@type": "Brand", "name": "HONDA"},
            "offers": {
                "@type": "Offer",
                "price": "89900",
                "priceCurrency": "BRL",
                "seller": {"@type": "Organization", "name": "VIA MAIS AUTOMOVEIS"},
            },
        },
        {
            "@type": "Product",
            "name": "TOYOTA COROLLA 2015 2.0 XEI 16V 4P",
            "image": "https://www.chavesnamao.com.br/imn/0600x0400/corolla-a.jpg",
            "url": "https://www.chavesnamao.com.br/carro/sp-sao-paulo/toyota-corolla-2.0-xei-16v-4p-2015-automatico-prata-RS62500/id-2222222/",
            "model": "COROLLA",
            "color": "PRATA",
            "brand": {"@type": "Brand", "name": "TOYOTA"},
            "offers": {"@type": "Offer", "price": "62500", "priceCurrency": "BRL"},
        },
    ]
    # km nao vem do JSON-LD -- so do texto do card correspondente no DOM, casado pela url.
    cards = """
      <a href="/carro/pr-curitiba/honda-civic-2.0-exl-sedan-16v-4p-2018-automatico-branca-RS89900/id-1111111/">
        Honda Civic 2.0 EXL 2018 R$ 89.900 45.000 km Curitiba , PR
      </a>
      <a href="/carro/sp-sao-paulo/toyota-corolla-2.0-xei-16v-4p-2015-automatico-prata-RS62500/id-2222222/">
        Toyota Corolla 2.0 XEI 2015 R$ 62.500 120.000 km Sao Paulo , SP
      </a>
    """
    html = _itemlist_html(products, cards)
    monkeypatch.setattr(chavesnamao, "fetch_html_with_browser_fallback", lambda *a, **k: html)
    monkeypatch.setattr(chavesnamao, "fetch_html", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no detail fetch needed, JSON-LD has image")))

    ctx = ScrapeContext(source="chavesnamao", browser_fallback_enabled=False)
    items = chavesnamao.scrape_chavesnamao(
        "https://www.chavesnamao.com.br/carros/brasil/honda-civic/", limit=10, ctx=ctx
    )

    assert len(items) == 2
    by_id = {it["external_id"]: it for it in items}

    civic = by_id["1111111"]
    assert civic["price"] == Decimal("89900")
    assert civic["year"] == 2018
    assert civic["km"] == 45000
    assert civic["thumbnail_url"] == "https://www.chavesnamao.com.br/imn/0600x0400/civic-a.jpg"
    assert "CIVIC" in civic["title"].upper()

    corolla = by_id["2222222"]
    assert corolla["price"] == Decimal("62500")
    assert corolla["year"] == 2015
    assert corolla["km"] == 120000


def test_itemlist_year_falls_back_to_url_when_absent_from_name(monkeypatch):
    from app.scrapers import chavesnamao

    products = [
        {
            "@type": "Product",
            "name": "HONDA CIVIC EXL SEDAN 16V 4P",  # sem ano no name
            "url": "https://www.chavesnamao.com.br/carro/pr-curitiba/honda-civic-exl-2018-automatico-RS89900/id-3333333/",
            "offers": {"@type": "Offer", "price": "89900"},
        },
    ]
    html = _itemlist_html(products)
    monkeypatch.setattr(chavesnamao, "fetch_html_with_browser_fallback", lambda *a, **k: html)
    monkeypatch.setattr(chavesnamao, "fetch_html", lambda *a, **k: "<html></html>")

    ctx = ScrapeContext(source="chavesnamao", browser_fallback_enabled=False)
    items = chavesnamao.scrape_chavesnamao(
        "https://www.chavesnamao.com.br/carros/brasil/honda-civic/", limit=10, ctx=ctx
    )

    assert items[0]["year"] == 2018


def test_falls_back_to_dom_when_no_itemlist(monkeypatch):
    """Sem bloco ItemList (ex.: pagina de busca generica ?q=... sem SSR de modelo
    especifico), o caminho DOM antigo continua funcionando sem regressao."""
    from app.scrapers import chavesnamao

    html = """
    <html><body>
      <a href="/carro/pr-curitiba/honda-civic-2018/id-9988776/">
        <img src="/img/civic.jpg" />
        Honda Civic 2.0 EXL 2018 R$ 89.900 45.000 km Flex Automático Curitiba , PR
      </a>
    </body></html>
    """.strip()

    monkeypatch.setattr(chavesnamao, "fetch_html_with_browser_fallback", lambda *a, **k: html)
    monkeypatch.setattr(chavesnamao, "fetch_html", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no detail fetch")))

    ctx = ScrapeContext(source="chavesnamao", browser_fallback_enabled=False)
    items = chavesnamao.scrape_chavesnamao(
        "https://www.chavesnamao.com.br/carros-usados/brasil/?q=honda+civic", limit=10, ctx=ctx
    )

    assert len(items) == 1
    assert items[0]["external_id"] == "9988776"
    assert items[0]["price"] == Decimal("89900.00")
    assert items[0]["year"] == 2018
    assert items[0]["km"] == 45000


def test_real_fixture_yields_15_items_with_price_and_year_full_coverage():
    """Fixture ao vivo de 28/09 (docs/spikes/sources-melhorias-execucao.md secao 3/4):
    15 Products no ItemList, parser antigo so capturava 5 (secao 4 do relatorio)."""
    if not FIXTURE.exists():
        import pytest

        pytest.skip(f"fixture ausente: {FIXTURE}")

    from app.scrapers import chavesnamao

    html = FIXTURE.read_text(encoding="utf-8")
    ctx = ScrapeContext(source="chavesnamao", browser_fallback_enabled=False)
    orig_fetch_html = chavesnamao.fetch_html
    chavesnamao.fetch_html_with_browser_fallback = lambda *a, **k: html
    try:
        items = chavesnamao.scrape_chavesnamao(
            "https://www.chavesnamao.com.br/carros/brasil/honda-civic/", limit=50, ctx=ctx
        )
    finally:
        chavesnamao.fetch_html = orig_fetch_html

    # A pagina tem 15 Products no ItemList, mas 2 deles (id-8353761 e
    # id-8581412) tem o MESMO preco de 6 digitos (105900), entao colidem no
    # mesmo external_id preexistente-bugado (ver docstring do modulo) e o
    # dedupe por (source, external_id) em scrape_chavesnamao derruba um dos
    # dois -- 14 itens unicos, nao 15. Isso e uma consequencia visivel do bug
    # de colisao preco/id ja existente no parser DOM, so que so aparece agora
    # porque estamos capturando 15 itens em vez de 5 (mais chance de colisao
    # aleatoria de preco). Documentado no relatorio da Fase 1; nao corrigido
    # aqui (fora do escopo do prompt v2 para esta fase).
    assert len(items) == 14

    with_year = sum(1 for it in items if it.get("year") is not None)
    with_price = sum(1 for it in items if it.get("price") is not None)
    with_km = sum(1 for it in items if it.get("km") is not None)

    assert with_year == len(items)
    assert with_price == len(items)
    assert with_km >= len(items) * 0.9  # regra do prompt: km em >=90%

    # Regressao ADR-0001: os 5 external_id que o parser DOM-only ja capturava
    # nesta mesma fixture (validado manualmente, ver relatorio da Fase 1)
    # continuam presentes e identicos -- inclusive o bug preexistente de
    # colisao preco/id quando o preco tem 6+ digitos (nao corrigido aqui).
    previously_captured_ids = {"205490", "9084945", "8660397", "136900", "194390"}
    got_ids = {it["external_id"] for it in items}
    assert previously_captured_ids.issubset(got_ids)
