from __future__ import annotations

from app.scrapers.chavesnamao import build_chavesnamao_search_url


def test_pagination_uses_pg_param_allowed_by_robots_txt():
    """chavesnamao.com.br robots.txt bloqueia toda query string (Disallow: /*?*)
    exceto `?pg=2$`..`?pg=5$` e `?relatedAds=true$` (confirmado ao vivo, 2026-09).
    O parametro antigo `?pagina=N` nao esta na lista de excecoes -> violacao."""
    url = build_chavesnamao_search_url("toyota corolla", page=2)
    assert "pg=2" in url
    assert "pagina=" not in url


def test_pagination_beyond_page_5_is_not_crawlable_and_is_dropped():
    """Nenhuma pagina alem de 5 e permitida pelo robots.txt para busca por query
    string, entao nao ha parametro compliant para gerar -- mantemos a URL base."""
    base = build_chavesnamao_search_url("toyota corolla", page=1)
    beyond = build_chavesnamao_search_url("toyota corolla", page=6)
    assert beyond == base
    assert "pg=" not in beyond
