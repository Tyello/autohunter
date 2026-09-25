import json
from types import SimpleNamespace
from unittest.mock import patch

from app.scrapers.kavak import scrape_kavak

_SEARCH_URL = "https://www.kavak.com/br/seminovos"
_CTX = SimpleNamespace(proxy_server=None)

_CAR_URL = "https://www.kavak.com/br/venda/chevrolet-onix_plus-10_turbo_premier_auto-sedan-2020"

_CARS_JSON = json.dumps(
    [
        {
            "id": "550075",
            "url": _CAR_URL,
            "title": "Chevrolet Onix Plus",
            "subtitle": "2020 - 57.793 km - 1.0 TURBO PREMIER AUTO - Automático",
            "mainPrice": "73.299",
            "symbol": "R$",
            "analytics": {
                "car_make": "Chevrolet",
                "car_model": "Onix Plus",
                "car_price": "73299",
                "car_location": "São Paulo",
                "car_id": "550075",
                "car_year": 2020,
            },
        }
    ]
)

# Mirrors the real self.__next_f.push([1, "<escaped JSON string>"]) RSC chunk shape.
_RAW_CHUNK = '34:{"data":{"results":{"resultsQuantity":"1 Resultado","cars":%s}}}' % _CARS_JSON
_ESCAPED_CHUNK = json.dumps(_RAW_CHUNK)[1:-1]  # strip the wrapping quotes json.dumps adds

_HTML = f"""
<html><body>
<a href="/br/venda/chevrolet-onix_plus-10_turbo_premier_auto-sedan-2020">
  <div><h3>Chevrolet Onix Plus</h3><span>R$ 73.299</span></div>
</a>
<script>self.__next_f.push([1,"{_ESCAPED_CHUNK}"])</script>
</body></html>
"""


class _FakeBrowserResult:
    def __init__(self, html):
        self.html = html
        self.final_url = _SEARCH_URL


def test_scrape_kavak_enriches_km_and_year_from_rsc_payload():
    with patch(
        "app.scrapers.kavak.fetch_html_browser",
        return_value=_FakeBrowserResult(_HTML),
    ):
        listings = scrape_kavak(_SEARCH_URL, ctx=_CTX)

    assert len(listings) == 1
    item = listings[0]
    assert item["url"] == _CAR_URL
    assert item["year"] == 2020
    assert item["km"] == 57793
