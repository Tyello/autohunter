"""Fase 2 (docs/prompts/PROMPT-exec-melhorias-sources-v2.md): scrape_kavak
trocou fetch_html_browser direto por fetch_html_with_browser_fallback
(app/scrapers/kavak.py), preparando o caminho HTTP-first sem virar em
producao (force_browser continua True no default de seed, nao alterado
nesta fase -- ver app/sources/builtins.py).

Este teste cobre o gate da Fase 2: rodar o scraper contra a fixture real da
Fase 0 (tests/fixtures/source_regression/kavak/2026-09-28_civic/listing.html)
por um caminho puramente HTTP (ctx.force_browser=False, sem nenhum acesso a
browser), confirmando que o RSC (_extract_rsc_cars) sozinho -- sem qualquer
fetch de browser -- ja produz price/year/km/location, e que external_id
continua a mesma regra de sempre (ADR-0001, nada mudou em _external_id_from_url)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.scrapers.kavak import scrape_kavak
from app.sources.types import ScrapeContext

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "source_regression"
    / "kavak"
    / "2026-09-28_civic"
    / "listing.html"
)


def test_http_first_path_never_touches_browser_and_matches_baseline():
    if not FIXTURE.exists():
        pytest.skip(f"fixture ausente: {FIXTURE}")

    html = FIXTURE.read_text(encoding="utf-8")
    ctx = ScrapeContext(source="kavak", force_browser=False, browser_fallback_enabled=False)

    def _boom_if_browser_called(*a, **k):
        raise AssertionError("scrape_kavak nao deveria tocar o browser neste cenario (force_browser=False, sem bloqueio HTTP)")

    with patch("app.scrapers.kavak.fetch_html_with_browser_fallback", return_value=html) as mocked_fetch, \
         patch("app.services.browser_fetcher.fetch_html_browser", side_effect=_boom_if_browser_called):
        items = scrape_kavak(
            "https://www.kavak.com/br/seminovos/honda-civic", ctx=ctx
        )

    # Confirma que o fetch usado foi o hibrido (HTTP-first), nao o browser puro.
    mocked_fetch.assert_called_once()

    assert len(items) == 9  # baseline da Fase 0 (relatorio, secao 4): 9 encontrados

    with_price = sum(1 for it in items if it.get("price") is not None)
    with_year = sum(1 for it in items if it.get("year") is not None)
    with_km = sum(1 for it in items if it.get("km") is not None)
    with_location = sum(1 for it in items if it.get("location") is not None)

    # Baseline da Fase 0 (docs/spikes/sources-melhorias-execucao.md, secao 4):
    # price/year/km/location 100% via RSC -- sem nenhum dado de browser.
    assert with_price == len(items)
    assert with_year == len(items)
    assert with_km == len(items)
    assert with_location == len(items)

    # external_id: mesma regra de sempre (_external_id_from_url, sem mudanca nesta fase).
    for it in items:
        assert it["external_id"], "external_id nao pode ficar vazio"
        assert "/br/venda/" in it["url"]
