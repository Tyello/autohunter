from __future__ import annotations

from pathlib import Path

from app.scrapers.olx import _extract_items_from_next_data, _extract_rsc_json_chunks


def test_real_fixture_year_km_read_from_structured_properties():
    """OLX embute specs estruturadas em node['properties'] (name="regdate"/"mileage"),
    mais confiavel que regex sobre o titulo (que nao tem km e so acerta ano quando o
    ano aparece no texto do titulo). Fixture real capturada de uma pagina de busca
    (tests/fixtures/olx/search_rsc_price_nodes.html): Honda Fit 2021 com 33.200 km e
    Honda Fit 2005 com 200.000 km, nenhum dos dois com km no titulo."""
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "search_rsc_price_nodes.html"
    html = fixture_path.read_text(encoding="utf-8")

    chunks = _extract_rsc_json_chunks(html)
    items = _extract_items_from_next_data(chunks)
    by_id = {it.external_id: it for it in items}

    assert by_id["1503037487"].year == 2021
    assert by_id["1503037487"].km == 33200
    assert by_id["1512208902"].year == 2005
    assert by_id["1512208902"].km == 200000
