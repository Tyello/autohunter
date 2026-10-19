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


def test_unknown_page_without_items_is_still_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(olx_mod, "health_dir", lambda: tmp_path)
    with pytest.raises(FetchBlocked) as exc:
        _run(monkeypatch, UNKNOWN_HTML)
    # diagnostico: motivo e tamanho vao no evento source_blocked; trecho do HTML e guardado
    assert exc.value.reason == "empty_or_unparseable"
    assert exc.value.html_length == len(UNKNOWN_HTML)
    assert "algo inesperado" in (tmp_path / "olx_unparseable_last.html").read_text(encoding="utf-8")


def test_challenge_page_is_never_treated_as_empty(monkeypatch):
    # _fetch_http_hybrid ja levantaria FetchBlocked p/ desafio; aqui garantimos que o
    # marcador de vazio sozinho nao mascara uma pagina de bot que escapou.
    assert olx_mod._is_empty_results_page(CHALLENGE_HTML) is False


def test_large_page_without_items_or_bot_signal_is_empty_and_dumped(monkeypatch, tmp_path):
    monkeypatch.setattr(olx_mod, "health_dir", lambda: tmp_path)
    big = "<html><body>" + ("<div>conteudo sem anuncios parseaveis</div>" * 5000) + "</body></html>"
    assert len(big) >= olx_mod._OLX_FULL_PAGE_MIN_CHARS
    assert _run(monkeypatch, big) == []
    dumped = (tmp_path / "olx_unparseable_last.html").read_text(encoding="utf-8")
    assert dumped.startswith("<!-- url=https://www.olx.com.br/")
    assert len(dumped) < 9000


def test_large_challenge_page_is_still_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(olx_mod, "health_dir", lambda: tmp_path)
    big = "<html><title>Just a moment...</title>" + ("<div>x</div>" * 20000) + "</html>"
    # desafio e barrado antes (fetch hybrid); aqui simulamos o parse caindo no ramo sem itens
    with pytest.raises(FetchBlocked) as exc:
        olx_mod._no_items_result(big, "https://www.olx.com.br/x")
    assert exc.value.reason == "bot_challenge"
    assert exc.value.html_length == len(big)
    assert "Just a moment" in (tmp_path / "olx_unparseable_last.html").read_text(encoding="utf-8")


def test_olx_first_block_backoff_is_120_minutes():
    from app.services.source_execution_service import _base_cooldown_minutes_for, _max_backoff_minutes_for
    from app.services.source_backoff_service import _compute_backoff_minutes

    cfg = SimpleNamespace(cooldown_minutes=0)
    base = _base_cooldown_minutes_for("olx", cfg)
    cap = _max_backoff_minutes_for("olx")
    assert base == 120
    assert [_compute_backoff_minutes(base, n, cap) for n in (1, 2, 3, 4, 5)] == [120, 240, 480, 960, 1440]


def test_cloudflare_block_page_reaching_no_items_path_is_bot_challenge(monkeypatch, tmp_path):
    # prod 19/10: pagina "Sorry, you have been blocked" (browser fallback) saia como empty_or_unparseable
    monkeypatch.setattr(olx_mod, "health_dir", lambda: tmp_path)
    page = "<html><title>Attention Required! | Cloudflare</title>Sorry, you have been blocked</html>"
    with pytest.raises(FetchBlocked) as exc:
        olx_mod._no_items_result(page, "https://www.olx.com.br/x")
    assert exc.value.reason == "bot_challenge"
