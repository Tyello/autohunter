"""Regressao: busca do OLX sem nenhum resultado ("Ops! Nenhum anuncio foi encontrado",
totalOfAds:0) devolve 200 legitimo, mas scrape_olx levantava FetchBlocked(empty_or_unparseable)
e a source inteira entrava em backoff de 24h (prod 09/10: wishlist "A5 ambition plus" derrubou
o OLX mesmo com as outras buscas retornando 50 anuncios).

Pagina de resultado vazio deve retornar []; pagina sem itens e sem marcador de vazio
continua sendo tratada como bloqueio."""

from types import SimpleNamespace

import pytest

from app.scrapers import olx as olx_mod
from app.scrapers.base import FetchBlocked

EMPTY_HTML = (
    '<html><head><title>"A5 ambition plus" - Carros Usados</title></head><body>'
    '<span class="typo-title-large">Ops! Nenhum anúncio foi encontrado.</span>'
    '<p>0 - 0 de 0 resultados</p>'
    '<script>{"keyword":"A5 ambition plus"},"totalOfAds":0,"main_category":"Autos"}</script>'
    "</body></html>"
)
UNKNOWN_HTML = "<html><body><p>algo inesperado sem itens</p></body></html>"
CHALLENGE_HTML = "<html><title>Attention Required! | Cloudflare</title>Nenhum anúncio foi encontrado</html>"


def _ctx():
    return SimpleNamespace(source="olx", proxy_server=None, force_browser=False)


def _run(monkeypatch, html):
    monkeypatch.setattr(olx_mod, "_fetch_http_hybrid", lambda *a, **k: html)
    monkeypatch.setattr(olx_mod.settings, "olx_force_browser", False, raising=False)
    monkeypatch.setattr(olx_mod, "_runtime_force_browser_active", lambda: False)
    return olx_mod.scrape_olx("https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q=x", _ctx())


def test_empty_results_page_returns_empty_list(monkeypatch):
    assert _run(monkeypatch, EMPTY_HTML) == []


def test_unknown_page_without_items_is_still_blocked(monkeypatch):
    with pytest.raises(FetchBlocked):
        _run(monkeypatch, UNKNOWN_HTML)


def test_challenge_page_is_never_treated_as_empty(monkeypatch):
    # _fetch_http_hybrid ja levantaria FetchBlocked p/ desafio; aqui garantimos que o
    # marcador de vazio sozinho nao mascara uma pagina de bot que escapou.
    assert olx_mod._is_empty_results_page(CHALLENGE_HTML) is False
