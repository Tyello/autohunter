from types import SimpleNamespace
from unittest.mock import patch

from app.scrapers.mobiauto import _detail_enrich

_CTX = SimpleNamespace(proxy_server=None)


def test_detail_enrich_strips_disallowed_page_detail_param():
    """mobiauto.com.br robots.txt disallows `/comprar/carros*?*page=detail`.

    `_detail_enrich` must not request that exact query shape, even though
    the listing URL shown to users keeps `?page=detail` unchanged.
    """
    url = (
        "https://www.mobiauto.com.br/comprar/carros/sp-caraguatatuba/ram/"
        "rampage/2027/bighorn-2-2-turbodiesel/detalhes/31610427?page=detail"
    )

    with patch("app.scrapers.mobiauto.fetch_html_with_browser_fallback") as mocked_fetch:
        mocked_fetch.return_value = "<html></html>"
        _detail_enrich(url, ctx=_CTX)

    fetched_url = mocked_fetch.call_args[0][0]
    assert "page=detail" not in fetched_url
    assert fetched_url.startswith(
        "https://www.mobiauto.com.br/comprar/carros/sp-caraguatatuba/ram/"
        "rampage/2027/bighorn-2-2-turbodiesel/detalhes/31610427"
    )


def test_detail_enrich_preserves_other_query_params():
    url = "https://www.mobiauto.com.br/comprar/carros/foo/detalhes/123?page=detail&sop=showroom"

    with patch("app.scrapers.mobiauto.fetch_html_with_browser_fallback") as mocked_fetch:
        mocked_fetch.return_value = "<html></html>"
        _detail_enrich(url, ctx=_CTX)

    fetched_url = mocked_fetch.call_args[0][0]
    assert "page=detail" not in fetched_url
    assert "sop=showroom" in fetched_url
