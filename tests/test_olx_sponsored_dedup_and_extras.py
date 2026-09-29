"""Fase 3 (docs/prompts/PROMPT-exec-melhorias-sources-v2.md): OLX - limpeza.

1. Duplicatas por listId (item destacado/patrocinado repetido, ex.: uma vez no
   carrossel "fixedOnTop" e de novo na grade normal de resultados) nao devem
   virar 2 anuncios nem sumir -- exatamente 1, mantendo os dados do primeiro
   nó encontrado. NAO reproduzi esse cenario na fixture real da Fase 0
   (tests/fixtures/source_regression/olx/2026-09-28_civic/listing.html) --
   ela nao tem nenhum node com fixedOnTop/professionalAd (confirmado via
   grep), entao este teste usa dados sinteticos pra fixar o comportamento
   (o dedup por `external_id`, ja existente em `_extract_items_from_next_data`,
   ja cobria isso -- este teste so torna a cobertura explicita).

2. gearbox/fuel/professionalAd das `properties` viram campos extras, sem
   mudanca de schema: "gearbox"/"fuel_type" ja sao chaves reconhecidas por
   app/sources/normalize.py (mapeiam pra transmission/fuel_type existentes);
   "professionalAd" cai no catch-all `extras` (JSONB ja existente)."""

from __future__ import annotations

from app.scrapers.olx import _extract_items_from_next_data, _items_to_dicts


def _node(list_id: int, *, fixed_on_top: bool = False, professional_ad: bool | None = None, price: int = 89900) -> dict:
    node = {
        "listId": list_id,
        "friendlyUrl": f"https://www.olx.com.br/item/honda-civic-{list_id}",
        "subject": "Honda Civic 2018",
        "priceValue": f"R$ {price}",
        "properties": [
            {"name": "regdate", "value": "2018", "label": "Ano"},
            {"name": "mileage", "value": "45.000 km", "label": "Quilometragem"},
            {"name": "gearbox", "value": "Automático", "label": "Câmbio"},
            {"name": "fuel", "value": "Híbrido", "label": "Combustível"},
        ],
    }
    if fixed_on_top:
        node["fixedOnTop"] = True
    if professional_ad is not None:
        node["professionalAd"] = professional_ad
    return node


def test_sponsored_duplicate_listid_kept_once_not_discarded():
    # Mesmo carro aparece 2x: uma vez destacado (fixedOnTop) no topo da
    # pagina, outra vez na grade normal de resultados -- mesmo listId.
    tree = {
        "data": [
            _node(1234567, fixed_on_top=True, professional_ad=True),
            _node(1234567, fixed_on_top=False),  # mesma ad, ocorrencia normal
            _node(7654321),  # ad distinta, nao deve ser afetada
        ]
    }

    items = _extract_items_from_next_data(tree)

    ids = [it.external_id for it in items]
    assert ids.count("1234567") == 1, "duplicata por listId nao pode virar 2 itens"
    assert "7654321" in ids, "a ad distinta nao pode ser descartada"
    assert len(items) == 2

    # Mantém os dados do primeiro node encontrado (o destacado), não descarta o anúncio.
    kept = next(it for it in items if it.external_id == "1234567")
    assert kept.year == 2018
    assert kept.km == 45000


def test_gearbox_fuel_professional_ad_extracted_as_extras():
    tree = {"data": [_node(1234567, professional_ad=True)]}
    items = _extract_items_from_next_data(tree)
    out = _items_to_dicts(items)

    item = out[0]
    assert item["gearbox"] == "Automático"
    assert item["fuel_type"] == "Híbrido"
    assert item["professionalAd"] is True


def test_gearbox_fuel_flow_through_normalize_ad_without_schema_change():
    """Confirma que os valores pt-br crus (ex. "Automático"/"Híbrido") viram
    os enums canonicos existentes (transmission/fuel_type) no pipeline
    v1 compartilhado (app/sources/normalize.py), sem precisar de coluna nova."""
    from app.sources.normalize import normalize_ad

    tree = {"data": [_node(1234567, professional_ad=True)]}
    items = _extract_items_from_next_data(tree)
    raw = _items_to_dicts(items)[0]

    ad = normalize_ad("olx", raw)

    assert ad.extras["transmission"] == "automatic"
    assert ad.extras["fuel_type"] == "hybrid"
    # professionalAd nao tem campo dedicado -- cai no catch-all extras.
    assert ad.extras.get("professionalAd") is True


def test_real_fixture_still_zero_duplicate_listids_and_year_km_unaffected():
    """Gate da Fase 3: zero listId duplicado na fixture real, year/km
    mantidos em 100% (a fixture nao tem cenario de fixedOnTop/professionalAd,
    mas o dedup e os novos campos extras nao podem regredir o que ja
    funcionava)."""
    from pathlib import Path

    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "source_regression"
        / "olx"
        / "2026-09-28_civic"
        / "listing.html"
    )
    if not fixture.exists():
        import pytest

        pytest.skip(f"fixture ausente: {fixture}")

    from app.scrapers.olx import _extract_rsc_json_chunks

    html = fixture.read_text(encoding="utf-8")
    chunks = _extract_rsc_json_chunks(html)
    items = _extract_items_from_next_data(chunks)
    out = _items_to_dicts(items)

    ids = [it["external_id"] for it in out]
    assert len(ids) == len(set(ids)), "nao pode haver listId duplicado"
    assert len(out) == 50

    with_year = sum(1 for it in out if it.get("year") is not None)
    with_km = sum(1 for it in out if it.get("km") is not None)
    assert with_year == len(out)
    assert with_km == len(out)
