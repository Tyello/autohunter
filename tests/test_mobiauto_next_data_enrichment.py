import json
from types import SimpleNamespace
from unittest.mock import patch

from app.scrapers.mobiauto import scrape_mobiauto

_SEARCH_URL = "https://www.mobiauto.com.br/comprar/carros/brasil"
_CTX = SimpleNamespace(proxy_server=None)

_NEXT_DATA = {
    "props": {
        "pageProps": {
            "deals": {
                "results": [
                    {
                        "id": "31610427",
                        "price": 208900,
                        "km": 0,
                        "trim": {
                            "productionYear": 2026,
                            "model": {"name": "Rampage", "year": 2027},
                            "make": {"name": "Ram"},
                        },
                    }
                ]
            }
        }
    }
}

_HTML = f"""
<html><body>
<a href="/comprar/carros/sp-caraguatatuba/ram/rampage/2027/bighorn/detalhes/31610427?page=detail">
  Ram Rampage BigHorn
</a>
<script id="__NEXT_DATA__" type="application/json">{json.dumps(_NEXT_DATA)}</script>
</body></html>
"""


def test_scrape_mobiauto_enriches_year_and_km_from_next_data():
    with patch(
        "app.scrapers.mobiauto.fetch_html_with_browser_fallback",
        return_value=_HTML,
    ):
        listings = scrape_mobiauto(_SEARCH_URL, ctx=_CTX)

    assert len(listings) == 1
    item = listings[0]
    assert item["external_id"] == "31610427"
    assert item["year"] == 2026
    assert item["km"] == 0
    assert item["price"] == 208900
