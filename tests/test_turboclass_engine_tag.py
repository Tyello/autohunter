"""Fase 4 (docs/prompts/PROMPT-exec-melhorias-sources-v2.md): TurboClass expõe
a MOTORIZAÇÃO do card (Turbo/Original/etc, variável `spec` em
app/scrapers/turboclass.py) como campo extra `engine_tag` -- antes só era
usada pra compor o título, sem ficar acessível como campo estruturado.
Sem mudança de schema: "engine_tag" não é reconhecida por
app/sources/normalize.py, cai no catch-all `extras` (JSONB já existente)."""

from __future__ import annotations

from pathlib import Path

from app.scrapers.turboclass import scrape_turboclass

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "source_regression"
    / "turboclass"
    / "2026-09-28_civic"
    / "listing.html"
)


def test_engine_tag_present_in_real_fixture(monkeypatch):
    if not FIXTURE.exists():
        import pytest

        pytest.skip(f"fixture ausente: {FIXTURE}")

    import app.scrapers.turboclass as mod

    html = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(mod, "fetch_html_with_browser_fallback", lambda url, ctx=None: html)

    items = scrape_turboclass("https://turboclass.com.br/anuncio-lista.php?q=honda+civic")

    assert len(items) == 27  # baseline ja confirmado (Fase 0/investigacao turboclass)
    with_engine_tag = sum(1 for it in items if it.get("engine_tag"))
    assert with_engine_tag == len(items)
    # amostra: primeiro item da fixture e "Honda Civic SI Turbo 2007"
    assert items[0]["engine_tag"] == "Turbo"


def test_engine_tag_flows_through_normalize_ad_as_extra_without_schema_change():
    from app.sources.normalize import normalize_ad

    raw = {
        "source": "turboclass",
        "external_id": "tc-test123",
        "url": "https://turboclass.com.br/anuncio/detalhe/tc-test123",
        "title": "Honda Civic SI Turbo 2007",
        "price": 165900,
        "year": 2007,
        "make": "Honda",
        "model": "Civic",
        "engine_tag": "Turbo",
    }
    ad = normalize_ad("turboclass", raw)
    assert ad.extras.get("engine_tag") == "Turbo"
