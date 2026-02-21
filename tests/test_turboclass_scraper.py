from __future__ import annotations

from decimal import Decimal

from app.sources.types import ScrapeContext


def test_scrape_turboclass_parses_cards(monkeypatch):
    from app.scrapers import turboclass

    html = """
    <html><body>
      <a href="/anuncio/detalhe/tc-abc123-somente-venda-jetta-gli-turbo">
        <img src="/img/jetta.jpg" />
        Volkswagen Jetta Turbo Motorização VALOR R$ 115.000,00 ANO/MODELO 2017/2017 NEGÓCIO Aceita Troca LOCALIDADE São Paulo/SP detalhes
      </a>
      <a href="anuncio/detalhe/tc-def456-somente-venda-gol-turbo">
        Volkswagen Gol Turbo Motorização VALOR R$ 53.000,00 ANO/MODELO 2001/2001 NEGÓCIO Aceita Troca LOCALIDADE Osasco/SP detalhes
      </a>
    </body></html>
    """.strip()

    def _fake_fetch(url: str, *args, **kwargs) -> str:
        return html

    monkeypatch.setattr(turboclass, "fetch_html_with_browser_fallback", _fake_fetch)

    # se o enrichment tentar bater na página de detalhe, queremos falhar no teste
    def _no_detail_fetch(*args, **kwargs):
        raise AssertionError("detail fetch should not be needed when list has thumbnails")

    monkeypatch.setattr(turboclass, "fetch_html", _no_detail_fetch)

    ctx = ScrapeContext(source="turboclass", browser_fallback_enabled=False)
    items = turboclass.scrape_turboclass(
        "https://turboclass.com.br/anuncio-lista.php?o=&pg=1&q=jetta",
        ctx=ctx,
        limit=10,
    )

    assert len(items) == 2

    by_id = {it["external_id"]: it for it in items}

    a = by_id["tc-abc123"]
    assert a["source"] == "turboclass"
    assert a["title"] == "Volkswagen Jetta Turbo"
    assert a["url"].endswith("/tc-abc123-somente-venda-jetta-gli-turbo")
    assert a["price"] == Decimal("115000.00")
    assert a["location"] == "São Paulo/SP"
    assert a["year"] == 2017
    assert a["thumbnail_url"] == "https://turboclass.com.br/img/jetta.jpg"

    b = by_id["tc-def456"]
    assert b["title"] == "Volkswagen Gol Turbo"
    assert b["price"] == Decimal("53000.00")
    assert b["location"] == "Osasco/SP"
    assert b["year"] == 2001
