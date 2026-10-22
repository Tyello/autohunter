"""ML so resolve o slug de busca quando ele casa com um modelo conhecido ('fit', 'fusca',
'rs5', 'land-rover-defender'); 'defender', 'audi-rs5' e 'a5-ambition-plus' devolvem uma
pagina de zero resultados (`"results":[]`). O scraper tenta slugs alternativos so nesse caso."""

import pytest

from app.scrapers.mercadolivre import (
    _fallback_search_urls,
    _is_ml_empty_results_page,
    scrape_mercadolivre,
)
from app.sources.types import ScrapeContext

BASE = "https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/"

EMPTY_PAGE = '<html><script>{"results":[],"shops":null,"intervention_info":{}}</script></html>'
EMPTY_PAGE_ESCAPED = '<html><script>{\\"results\\":[],\\"shops\\":null}</script></html>'
SHELL_PAGE = '<html><body><div id="root"></div></body></html>'
RESULTS_PAGE = """
<html><body>
<li class="ui-search-layout__item">
  <a class="ui-search-link" href="https://carro.mercadolivre.com.br/MLB-123456789-audi-rs5-_JM">
    <h2 class="ui-search-item__title">Audi RS5 2019</h2>
  </a>
  <span class="andes-money-amount__fraction">620.000</span>
</li>
</body></html>
"""


@pytest.mark.parametrize(
    "slug, expected",
    [
        ("audi-rs5", ["rs5"]),
        ("a5-ambition-plus", ["a5"]),
        ("audi-a5-ambition-plus", ["a5-ambition-plus", "a5"]),
        ("defender", ["land-rover-defender"]),
        ("cuore", []),
        ("rs5", []),
    ],
)
def test_fallback_search_urls(slug, expected):
    assert _fallback_search_urls(BASE + slug) == [BASE + s for s in expected]


def test_empty_results_page_detector():
    assert _is_ml_empty_results_page(EMPTY_PAGE)
    assert _is_ml_empty_results_page(EMPTY_PAGE_ESCAPED)
    assert not _is_ml_empty_results_page(SHELL_PAGE)
    assert not _is_ml_empty_results_page(RESULTS_PAGE)
    assert not _is_ml_empty_results_page("")


def _patch_fetch(monkeypatch, pages):
    calls = []

    def _fake_fetch(url, ctx=None, timeout=25):
        calls.append(url)
        return pages.get(url, EMPTY_PAGE)

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", _fake_fetch)
    return calls


def test_scrape_retries_with_alternative_slug_on_empty_results(monkeypatch):
    calls = _patch_fetch(monkeypatch, {BASE + "rs5": RESULTS_PAGE})
    items = scrape_mercadolivre(BASE + "audi-rs5", ScrapeContext(source="mercadolivre"))
    assert calls == [BASE + "audi-rs5", BASE + "rs5"]
    assert len(items) == 1


def test_scrape_does_not_retry_when_first_slug_has_results(monkeypatch):
    calls = _patch_fetch(monkeypatch, {BASE + "audi-rs5": RESULTS_PAGE})
    items = scrape_mercadolivre(BASE + "audi-rs5", ScrapeContext(source="mercadolivre"))
    assert calls == [BASE + "audi-rs5"]
    assert len(items) == 1


def test_scrape_does_not_retry_on_shell_page(monkeypatch):
    calls = _patch_fetch(monkeypatch, {BASE + "audi-rs5": SHELL_PAGE})
    assert scrape_mercadolivre(BASE + "audi-rs5", ScrapeContext(source="mercadolivre")) == []
    assert calls == [BASE + "audi-rs5"]


def test_scrape_gives_up_after_alternatives_are_empty(monkeypatch):
    calls = _patch_fetch(monkeypatch, {})
    assert scrape_mercadolivre(BASE + "audi-a5-ambition-plus", ScrapeContext(source="mercadolivre")) == []
    assert calls == [BASE + "audi-a5-ambition-plus", BASE + "a5-ambition-plus", BASE + "a5"]
