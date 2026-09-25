from __future__ import annotations

"""Cobertura de teste para app/scrapers/chavesnamao.py -- antes desta suite,
nao havia nenhum teste automatizado para o parsing desse scraper (achado
registrado em docs/spikes/scrapling-parser-spike.md, secao 3.1). HTML
sintetico inline, no mesmo padrao usado em test_turboclass_scraper.py,
construido a partir dos seletores reais do scraper (app/scrapers/chavesnamao.py):
`a[href]` com `/id-` no href e "R$" no texto do link (linha ~172), regra de
localizacao via URL/texto (linhas 106-142), thumbnail via img/srcset/background
(linha 74), e enriquecimento por og:image na pagina de detalhe (linha ~233)."""

from decimal import Decimal

from app.sources.types import ScrapeContext


def test_scrape_chavesnamao_parses_cards(monkeypatch):
    from app.scrapers import chavesnamao

    html = """
    <html><body>
      <a href="/carro/pr-curitiba/honda-civic-2018/id-9988776/">
        <img src="/img/civic.jpg" />
        Honda Civic 2.0 EXL 2018 R$ 89.900 45.000 km Flex Automático Curitiba , PR
      </a>
      <a href="/carro/sp-sao-paulo/toyota-corolla-2015/id-1122334/">
        Toyota Corolla 2.0 XEI 2015 R$ 62.500 120.000 km Flex Automático São Paulo , SP
      </a>
      <a href="/institucional/sobre-nos">
        Anuncie seu carro conosco
      </a>
      <a href="/carro/mg-uberlandia/similar-sem-preco/id-5566778/">
        Fiat Argo sem preço visível ainda
      </a>
    </body></html>
    """.strip()

    def _fake_fetch(url: str, *args, **kwargs) -> str:
        return html

    monkeypatch.setattr(chavesnamao, "fetch_html_with_browser_fallback", _fake_fetch)

    def _no_detail_fetch(*args, **kwargs):
        raise AssertionError("detail fetch nao deveria ser necessario quando o card ja tem thumb")

    monkeypatch.setattr(chavesnamao, "fetch_html", _no_detail_fetch)

    ctx = ScrapeContext(source="chavesnamao", browser_fallback_enabled=False)
    items = chavesnamao.scrape_chavesnamao(
        "https://www.chavesnamao.com.br/carros-usados/brasil/?q=honda+civic",
        limit=10,
        ctx=ctx,
    )

    # Anuncio institucional (sem /id-) e anuncio sem "R$" no texto (sem preco
    # visivel) devem ser filtrados -- so 2 dos 4 <a> viram itens.
    assert len(items) == 2

    by_id = {it["external_id"]: it for it in items}

    civic = by_id["9988776"]
    assert civic["source"] == "chavesnamao"
    assert civic["price"] == Decimal("89900.00")
    assert civic["location"] == "Curitiba-PR"
    assert civic["thumbnail_url"] == "https://www.chavesnamao.com.br/img/civic.jpg"
    assert civic["url"] == "https://www.chavesnamao.com.br/carro/pr-curitiba/honda-civic-2018/id-9988776/"
    assert "Honda Civic 2.0 EXL 2018" in civic["title"]

    corolla = by_id["1122334"]
    assert corolla["price"] == Decimal("62500.00")
    assert corolla["location"] == "Sao Paulo-SP"


def test_scrape_chavesnamao_dedupes_by_external_id(monkeypatch):
    from app.scrapers import chavesnamao

    html = """
    <html><body>
      <a href="/carro/pr-curitiba/honda-civic-2018/id-9988776/">Honda Civic R$ 89.900 Curitiba , PR</a>
      <a href="/carro/pr-curitiba/honda-civic-2018/id-9988776/?utm_source=x">Honda Civic R$ 89.900 Curitiba , PR</a>
    </body></html>
    """.strip()

    monkeypatch.setattr(chavesnamao, "fetch_html_with_browser_fallback", lambda *a, **k: html)
    monkeypatch.setattr(chavesnamao, "fetch_html", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no detail fetch")))

    ctx = ScrapeContext(source="chavesnamao", browser_fallback_enabled=False)
    items = chavesnamao.scrape_chavesnamao(
        "https://www.chavesnamao.com.br/carros-usados/brasil/?q=honda+civic",
        limit=10,
        ctx=ctx,
    )

    assert len(items) == 1
    assert items[0]["external_id"] == "9988776"


def test_scrape_chavesnamao_respects_limit(monkeypatch):
    from app.scrapers import chavesnamao

    cards = "".join(
        f'<a href="/carro/pr-curitiba/carro-{i}/id-{1000000 + i}/">Carro {i} R$ {10 + i}.000 Curitiba , PR</a>'
        for i in range(5)
    )
    html = f"<html><body>{cards}</body></html>"

    monkeypatch.setattr(chavesnamao, "fetch_html_with_browser_fallback", lambda *a, **k: html)
    monkeypatch.setattr(chavesnamao, "fetch_html", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no detail fetch")))

    ctx = ScrapeContext(source="chavesnamao", browser_fallback_enabled=False)
    items = chavesnamao.scrape_chavesnamao(
        "https://www.chavesnamao.com.br/carros-usados/brasil/?q=carro",
        limit=3,
        ctx=ctx,
    )

    assert len(items) == 3


def test_scrape_chavesnamao_enriches_missing_thumbnail_via_og_image(monkeypatch):
    """Cobre app/scrapers/chavesnamao.py:242 (frio) -- quando o card nao tem
    thumbnail no HTML de listagem, o scraper busca a pagina de detalhe e
    extrai og:image / twitter:image / <img src> como fallback."""
    from app.scrapers import chavesnamao

    listing_html = """
    <html><body>
      <a href="/carro/pr-curitiba/honda-civic-2018/id-9988776/">Honda Civic R$ 89.900 Curitiba , PR</a>
    </body></html>
    """.strip()

    detail_html = """
    <html><head>
      <meta property="og:image" content="https://www.chavesnamao.com.br/img/civic-detalhe.jpg" />
    </head><body></body></html>
    """.strip()

    monkeypatch.setattr(chavesnamao, "fetch_html_with_browser_fallback", lambda *a, **k: listing_html)

    detail_calls = []

    def _fake_detail_fetch(url, *args, **kwargs):
        detail_calls.append(url)
        return detail_html

    monkeypatch.setattr(chavesnamao, "fetch_html", _fake_detail_fetch)

    ctx = ScrapeContext(source="chavesnamao", browser_fallback_enabled=False)
    items = chavesnamao.scrape_chavesnamao(
        "https://www.chavesnamao.com.br/carros-usados/brasil/?q=honda+civic",
        limit=10,
        ctx=ctx,
    )

    assert len(items) == 1
    assert detail_calls == ["https://www.chavesnamao.com.br/carro/pr-curitiba/honda-civic-2018/id-9988776/"]
    assert items[0]["thumbnail_url"] == "https://www.chavesnamao.com.br/img/civic-detalhe.jpg"


def test_extract_location_from_url_handles_uf_city_slug():
    from app.scrapers.chavesnamao import _extract_location_from_url

    assert _extract_location_from_url("https://www.chavesnamao.com.br/carro/pr-curitiba/x/") == "Curitiba-PR"
    assert _extract_location_from_url("https://www.chavesnamao.com.br/carro/sp-sao-paulo/x/") == "Sao Paulo-SP"
    assert _extract_location_from_url("https://www.chavesnamao.com.br/institucional/sobre/") is None


def test_extract_location_from_anchor_text_picks_last_city_uf_pair():
    from app.scrapers.chavesnamao import _extract_location_from_anchor_text

    text = "223.000 km Gasolina Mecânico Curitiba , PR"
    assert _extract_location_from_anchor_text(text) == "Curitiba-PR"
    assert _extract_location_from_anchor_text("sem local nenhum aqui") is None
