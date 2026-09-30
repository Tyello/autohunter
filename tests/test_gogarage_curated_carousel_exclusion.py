"""Fase 4 (docs/prompts/PROMPT-exec-melhorias-sources-v2.md): GoGarage.

Rodando o parser real (scrape_gogarage) pela primeira vez contra a fixture
ao vivo da Fase 0 (tests/fixtures/source_regression/gogarage/2026-09-28_civic/
listing.html, nunca executado antes -- pendencia da Fase 0), o baseline deu
12 "resultados" pra busca "honda civic" -- mas 11 deles eram carros sem
nenhuma relacao com a busca (Renault Clio, Honda City, Nivus, Spin, Cruze,
Peugeot 207, Gol, Fiesta, Santana, Palio, Kadett). Confirmado por inspecao
do HTML: esses cards vem de #ggHomeCuratedSections (secoes "Mais recentes"/
"Boosts"/"Peças do marketplace" da home), que aparecem ANTES da grade real
de resultados (<div class="bc-resultsbar" id="resultados">...<div
id="resultsMount"></div>). A grade real e populada via JS/AJAX (POST
?action=search, ja documentado na auditoria de 25/09) e por isso vem vazia
no HTML estatico desta fixture especifica (capturada via curl simples, sem
navegador) -- o <div class="bc-kpi">Carregando os achados…</div> confirma.

Fix aplicado em app/scrapers/gogarage.py (_extract_from_anchors e o
re-lookup de card em scrape_gogarage): exclui qualquer <a href*="/ads/">
descendente de #ggHomeCuratedSections."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.scrapers.gogarage import _extract_from_anchors, scrape_gogarage
from app.sources.types import ScrapeContext

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "source_regression"
    / "gogarage"
    / "2026-09-28_civic"
    / "listing.html"
)


_SYNTHETIC_HTML = """
<html><body>
  <div class="gg-home-curated" id="ggHomeCuratedSections">
    <section class="gg-home-block" aria-label="Mais recentes">
      <article class="bc-card" data-ad-card="1">
        <a class="bc-media" href="/ads/renault-clio-2005"></a>
        <div class="bc-body">
          <h3 class="bc-title"><a href="/ads/renault-clio-2005">Renault Clio 2005</a></h3>
        </div>
      </article>
    </section>
    <section class="gg-home-block" id="ggHomeBoostsBlock" aria-label="Boosts">
      <article class="bc-card" data-ad-card="1">
        <a class="bc-media" href="/ads/honda-city-2022"></a>
        <div class="bc-body">
          <h3 class="bc-title"><a href="/ads/honda-city-2022">Honda City 2022</a></h3>
        </div>
      </article>
    </section>
  </div>
  <div class="bc-resultsbar" id="resultados">
    <div id="resultsMount">
      <article class="bc-card" data-ad-card="1">
        <a class="bc-media" href="/ads/civic-si-2007"><img src="https://cdn.gogarage.com.br/civic.jpg" /></a>
        <div class="bc-body">
          <h3 class="bc-title"><a href="/ads/civic-si-2007">Civic SI 2007 - Preparado</a></h3>
          <div class="bc-meta" aria-label="Resumo do anúncio">
            <span class="bc-meta-item"><i class="bi bi-calendar3"></i><span class="bc-meta-text">2007</span></span>
            <span class="bc-meta-item"><i class="bi bi-speedometer2"></i><span class="bc-meta-text">85.000 km</span></span>
            <span class="bc-meta-item bc-meta-loc"><i class="bi bi-geo-alt"></i><span class="bc-meta-text">Curitiba/PR</span></span>
          </div>
          <div class="bc-price-row"><div class="bc-price">R$ 79.900</div></div>
        </div>
      </article>
    </div>
  </div>
</body></html>
""".strip()


def test_extract_from_anchors_excludes_curated_carousel():
    urls = _extract_from_anchors(_SYNTHETIC_HTML)
    assert urls == ["https://www.gogarage.com.br/ads/civic-si-2007"]


def test_scrape_gogarage_ignores_curated_carousel_keeps_real_result():
    ctx = ScrapeContext(source="gogarage", browser_fallback_enabled=False)

    with patch("app.scrapers.gogarage.fetch_html", return_value=_SYNTHETIC_HTML), \
         patch("app.scrapers.gogarage.fetch_details") as mocked_details:
        items = scrape_gogarage(
            "https://www.gogarage.com.br/index.php?q=honda+civic", ctx=ctx
        )

    assert len(items) == 1
    item = items[0]
    assert item["external_id"] == "civic-si-2007"
    assert "Civic" in item["title"]
    assert item["year"] == 2007
    assert item["km"] == 85000
    assert item["location"] == "Curitiba/PR"
    # o card real ja tem tudo (titulo/preco/ano/thumb nao faltou) -- nao deveria
    # gastar orcamento de fetch_details.
    mocked_details.assert_not_called()


def test_real_fixture_yields_zero_items_no_off_topic_noise():
    """Gate da Fase 4 ('nenhum item fora do termo buscado'): nesta fixture
    especifica, a grade real de resultados vem vazia no HTML estatico (ver
    docstring do modulo) -- o resultado correto e 0 itens, nao 12 itens
    fora do tema. Zero e estritamente melhor que noise: nenhum anuncio sem
    relacao com "honda civic" e retornado."""
    if not FIXTURE.exists():
        import pytest

        pytest.skip(f"fixture ausente: {FIXTURE}")

    html = FIXTURE.read_text(encoding="utf-8")
    ctx = ScrapeContext(source="gogarage", force_browser=False, browser_fallback_enabled=False)

    with patch("app.scrapers.gogarage.fetch_html_with_browser_fallback", return_value=html), \
         patch("app.scrapers.gogarage.fetch_html", return_value=html):
        items = scrape_gogarage(
            "https://www.gogarage.com.br/index.php?q=honda+civic", ctx=ctx
        )

    assert items == []
