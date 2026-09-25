from types import SimpleNamespace
from unittest.mock import patch

from app.scrapers.icarros import scrape_icarros

_SEARCH_URL = "https://www.icarros.com.br/comprar/saopaulo-sp?q=civic"
_CTX = SimpleNamespace(proxy_server=None)

_DETAIL_URL = "https://www.icarros.com.br/comprar/sao-paulo-sp/honda/civic/2019/d123456"

_SEARCH_HTML = f"""
<html><body>
<a href="{_DETAIL_URL}">Honda Civic</a>
</body></html>
"""

_DETAIL_HTML = """
<html><head>
<meta property="og:title" content="Honda Civic EXL 2019 - São Paulo - SP - iCarros" />
</head><body>
<div>R$ 85.000</div>
<div>30.000 km rodados</div>
</body></html>
"""


class _FakeBrowserResult:
    def __init__(self, html, final_url):
        self.html = html
        self.final_url = final_url


def test_scrape_icarros_sets_year_and_km_as_extra_keys():
    with patch(
        "app.scrapers.icarros.fetch_html_browser",
        side_effect=[
            _FakeBrowserResult(_SEARCH_HTML, _SEARCH_URL),
            _FakeBrowserResult(_DETAIL_HTML, _DETAIL_URL),
        ],
    ):
        listings = scrape_icarros(_SEARCH_URL, ctx=_CTX)

    assert len(listings) == 1
    item = listings[0]
    assert item["year"] == 2019
    assert item["km"] == 30000
    # km must not be manually appended to the title anymore (repo layer does it)
    assert "km" not in (item["title"] or "").lower()
