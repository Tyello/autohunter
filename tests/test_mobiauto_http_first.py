"""Fase 2 (docs/prompts/PROMPT-exec-melhorias-sources-v2.md), gate: rodar
scrape_mobiauto num caminho puramente HTTP (ctx.force_browser=False, sem
tocar em browser nenhum) contra a fixture real da Fase 0
(tests/fixtures/source_regression/mobiauto/2026-09-28_civic/listing.html) e
confirmar que price/year/km ficam >= o baseline da Fase 0
(docs/spikes/sources-melhorias-execucao.md, secao 4: price 95%, year 100%,
km 91% -- medidos por um script simplificado que nao tinha o enriquecimento
de title/thumbnail via JSON desta fase). external_id nao muda (mesma regra
de sempre, _extract_external_id)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.scrapers.mobiauto import scrape_mobiauto

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "source_regression"
    / "mobiauto"
    / "2026-09-28_civic"
    / "listing.html"
)


def test_http_first_path_never_touches_browser_and_meets_baseline():
    if not FIXTURE.exists():
        pytest.skip(f"fixture ausente: {FIXTURE}")

    html = FIXTURE.read_text(encoding="utf-8")
    ctx = SimpleNamespace(proxy_server=None, force_browser=False, browser_fallback_enabled=False)

    with patch("app.scrapers.mobiauto.fetch_html_with_browser_fallback", return_value=html) as mocked_fetch, \
         patch("app.services.browser_fetcher.fetch_html_browser") as mocked_browser, \
         patch("app.scrapers.mobiauto._detail_enrich", return_value={"title": None, "thumbnail_url": None}) as mocked_detail:
        items = scrape_mobiauto(
            "https://www.mobiauto.com.br/comprar/carros/brasil/honda/civic", ctx=ctx
        )

    mocked_fetch.assert_called_once()
    mocked_browser.assert_not_called()

    # __NEXT_DATA__.deals.results tem 24 itens nesta fixture (confirmado com
    # json.loads direto no fixture); by_url dedupa por URL de detalhe.
    assert len(items) == 24

    with_price = sum(1 for it in items if it.get("price") is not None)
    with_year = sum(1 for it in items if it.get("year") is not None)
    with_km = sum(1 for it in items if it.get("km") is not None)
    with_title = sum(1 for it in items if it.get("title"))

    assert with_price / len(items) >= 0.95
    assert with_year / len(items) == 1.0
    assert with_km / len(items) >= 0.91

    # Fase 2: title agora tambem vem do __NEXT_DATA__ (trim.make/model/name),
    # entao fica em 100% mesmo sem nenhum dado real de DOM/detail-page (o
    # _detail_enrich foi mockado pra devolver None em ambos os campos).
    assert with_title == len(items)

    # Uma parte real dos itens ja sai com thumbnail_url so do JSON (sem
    # nenhuma requisicao extra) -- medido nesta fixture real: 7/24 (~29%,
    # quando o restante depende de item['images'] vir malformado/ausente no
    # __NEXT_DATA__). O resto cai no fallback caro de _detail_enrich, que
    # continua existindo -- esta fase so reduz quantos itens precisam dele,
    # nao elimina o fallback.
    with_thumbnail_from_json = sum(1 for it in items if it.get("thumbnail_url"))
    assert with_thumbnail_from_json >= len(items) * 0.25
    # _detail_enrich e limitado a 8 chamadas por run (needs[:8], backfill barato)
    assert mocked_detail.call_count == 8

    # external_id: mesma regra de sempre (_extract_external_id), nao mudou nesta fase.
    for it in items:
        assert it["external_id"]
        assert "/detalhes/" in it["url"]
