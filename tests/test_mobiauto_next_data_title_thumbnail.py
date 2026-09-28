"""Fase 2 (docs/prompts/PROMPT-exec-melhorias-sources-v2.md): title e
thumbnail passam a sair do __NEXT_DATA__ (trim.make/trim.model/trim.name e
item['images']) quando o DOM nao fornecer -- antes so price/km/year vinham
do JSON (app/scrapers/mobiauto.py:_extract_next_data_deals)."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from app.scrapers.mobiauto import (
    _extract_next_data_deals,
    _first_image_id_from_next_data,
    _mobiauto_image_url,
    scrape_mobiauto,
)

_SEARCH_URL = "https://www.mobiauto.com.br/comprar/carros/brasil"
_CTX = SimpleNamespace(proxy_server=None)

_IMAGES_BLOB = "[3]{imageId:int,position:int}\n711786622,0\n711786629,1\n711786633,2\n"

_NEXT_DATA = {
    "props": {
        "pageProps": {
            "deals": {
                "results": [
                    {
                        "id": "31987597",
                        "price": 68900,
                        "km": 220000,
                        "images": _IMAGES_BLOB,
                        "trim": {
                            "name": "LXS 1.8 16V i-VTEC (Flex)",
                            "productionYear": 2013,
                            "model": {"name": "Civic", "year": 2014},
                            "make": {"name": "Honda"},
                        },
                    }
                ]
            }
        }
    }
}


def test_first_image_id_from_next_data_picks_position_zero():
    assert _first_image_id_from_next_data(_IMAGES_BLOB) == "711786622"
    assert _first_image_id_from_next_data("") is None
    assert _first_image_id_from_next_data(None) is None
    assert _first_image_id_from_next_data("garbage without lines") is None


def test_mobiauto_image_url_builds_expected_cdn_pattern():
    url = _mobiauto_image_url("711786622")
    assert url == (
        "https://image1.mobiauto.com.br/images/api/images/v1.0/711786622"
        "/transform/fl_progressive,f_webp,q_70,w_640"
    )


def test_extract_next_data_deals_includes_title_and_thumbnail():
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(_NEXT_DATA)}</script>'
    deals = _extract_next_data_deals(html)

    deal = deals["31987597"]
    assert deal["title"] == "Honda Civic LXS 1.8 16V i-VTEC (Flex) 2013"
    assert deal["thumbnail_url"] == _mobiauto_image_url("711786622")


def test_scrape_mobiauto_fills_title_and_thumbnail_from_next_data_when_dom_has_none():
    # Card <a> sem titulo util nenhum (so "Ver detalhes") e sem <img> -- o DOM
    # sozinho nao daria title/thumbnail, tudo precisa vir do __NEXT_DATA__.
    html = f"""
    <html><body>
    <a href="/comprar/carros/sp-caraguatatuba/honda/civic/2014/lxs/detalhes/31987597?page=detail">
      Ver detalhes
    </a>
    <script id="__NEXT_DATA__" type="application/json">{json.dumps(_NEXT_DATA)}</script>
    </body></html>
    """

    with patch("app.scrapers.mobiauto.fetch_html_with_browser_fallback", return_value=html), \
         patch("app.scrapers.mobiauto._detail_enrich") as mocked_detail_enrich:
        listings = scrape_mobiauto(_SEARCH_URL, ctx=_CTX)

    assert len(listings) == 1
    item = listings[0]
    assert item["external_id"] == "31987597"
    assert item["title"] == "Honda Civic LXS 1.8 16V i-VTEC (Flex) 2013"
    assert item["thumbnail_url"] == _mobiauto_image_url("711786622")
    assert item["price"] == 68900
    assert item["km"] == 220000
    assert item["year"] == 2013

    # O JSON ja preencheu title/thumbnail -- o fallback caro de detalhe (1
    # requisicao HTTP extra por item) nao deveria ter sido chamado.
    mocked_detail_enrich.assert_not_called()
