from __future__ import annotations

from app.scrapers.sources.olx import OLXScraper


def test_build_search_url_never_touches_disallowed_api_path():
    """OLX robots.txt bloqueia `/api/` inteiro (`Disallow: /api/`, confirmado ao
    vivo, 2026-09). O adapter v2 usava `API_URL = .../api/v1/search/listings`
    como URL primaria de busca, violando essa regra. Como o adapter ja sabe
    parsear HTML (`_extract_from_html`), a URL de busca deve ser a pagina HTML
    publica, mesmo path usado pelo v1 em `search_urls_service.olx_url`."""
    scraper = OLXScraper()
    url = scraper.build_search_url("honda civic")

    assert "/api/" not in url
    assert url.startswith("https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios")
    assert "q=honda+civic" in url


def test_build_search_url_respects_custom_category():
    scraper = OLXScraper()
    url = scraper.build_search_url("civic", category="autos-e-pecas/motos")

    assert "/api/" not in url
    assert url.startswith("https://www.olx.com.br/autos-e-pecas/motos")
