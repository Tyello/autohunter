r"""Fase 1 (docs/prompts/PROMPT-exec-melhorias-sources-v2.md): Chaves na Mao
capturava so 5 de 15 anuncios por pagina de busca porque so olhava para
<a href> + regex de texto no DOM, ignorando o JSON-LD `ItemList` que a propria
pagina ja expoe com todos os 15 (confirmado no fixture ao vivo de 28/09,
tests/fixtures/source_regression/chavesnamao/2026-09-28_civic/listing.html).

Esta suite cobre: (1) ItemList como fonte primaria quando presente, com km
casado pelo texto do card correspondente (o JSON-LD nao tem km); (2) fallback
para o caminho DOM antigo quando nao ha ItemList; (3) o fixture real gerando
os 15 itens, todos com external_id unico e correto.

Nota historica: a Fase 1 original preservou de proposito um bug preexistente
de colisao de external_id (regex "primeiro numero com 6+ digitos na URL"
casando o preco em vez do "id-<N>" real, quando o preco tinha 6+ digitos),
por instrucao explicita do prompt v2 ("external_id identico ao atual"). O
Marcelo pediu a correcao depois (ver commit que ancora a regex em
"/id-(\d+)", mesmo padrao de app/scrapers/contract.py:_RE_CHAVES) -- os
testes abaixo refletem o comportamento ja corrigido."""

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
    r"""Fixture ao vivo de 28/09 (docs/spikes/sources-melhorias-execucao.md secao 3/4):
    15 Products no ItemList, parser antigo so capturava 5 (secao 4 do relatorio).

    Ate a correcao do bug de colisao external_id (pedida explicitamente pelo
    Marcelo apos a Fase 1), esse teste esperava 14 itens unicos -- 2 dos 15
    Products colidiam no mesmo external_id bugado (o preco "105900" batendo
    antes do "id-<N>" real na URL). Com a regex ancorada em "/id-(\d+)"
    (app/scrapers/chavesnamao.py, mesmo padrao de
    app/scrapers/contract.py:_RE_CHAVES), os 15 saem com external_id correto
    e unico -- nenhuma colisao."""
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

    assert len(items) == 15

    got_ids = [it["external_id"] for it in items]
    assert len(got_ids) == len(set(got_ids)), "external_id nao pode colidir entre anuncios distintos"

    # IDs reais (segmento /id-<N> da URL), confirmados um a um contra o
    # ItemList da fixture -- inclui os dois que antes colidiam no preco
    # "105900" (8353761 e 8581412), agora distintos e corretos.
    expected_ids = {
        "8353761", "8870545", "9072157", "8581412", "8663724", "8930167",
        "9084945", "8660397", "9081898", "9079257", "9070208", "8917437",
        "8767654", "8715434", "8932030",
    }
    assert set(got_ids) == expected_ids

    with_year = sum(1 for it in items if it.get("year") is not None)
    with_price = sum(1 for it in items if it.get("price") is not None)
    with_km = sum(1 for it in items if it.get("km") is not None)

    assert with_year == len(items)
    assert with_price == len(items)
    assert with_km >= len(items) * 0.9  # regra do prompt: km em >=90%
