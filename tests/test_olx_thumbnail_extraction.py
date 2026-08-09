import json

from app.scrapers.olx import (
    _enrich_missing_olx_thumbnails,
    _extract_items_from_next_data,
    _extract_olx_detail_thumbnail,
    _fallback_parse_from_cards,
)
from app.sources.types import ScrapeContext


def test_olx_thumbnail_from_next_data_original_webp_nested():
    data = {"props": {"ads": [{"listId": "123456", "friendlyUrl": "https://www.olx.com.br/item/123456", "subject": "Civic", "priceValue": "R$ 80.000", "pictures": [{"versions": [{"originalWebp": "//img.olx.com.br/a.webp"}]}]}]}}
    items = _extract_items_from_next_data(data)
    assert items[0].thumbnail_url == "https://img.olx.com.br/a.webp"


def test_olx_detail_thumbnail_from_og_image():
    html = '<meta property="og:image" content="https://img.olx.com.br/og.jpg">'
    assert _extract_olx_detail_thumbnail(html, "https://www.olx.com.br/item/1") == "https://img.olx.com.br/og.jpg"


def test_olx_detail_thumbnail_from_json_ld_list():
    html = '<script type="application/ld+json">%s</script>' % json.dumps({"image": ["https://img.olx.com.br/ld.webp"]})
    assert _extract_olx_detail_thumbnail(html, "https://www.olx.com.br/item/1") == "https://img.olx.com.br/ld.webp"


def test_olx_card_gallery_lazy_srcset():
    html = '''<a data-testid="adcard-link" href="https://www.olx.com.br/item/987654">Corolla</a>
    <div><picture><source srcset="https://img.olx.com.br/lazy.webp 1x, https://img.olx.com.br/lazy2.webp 2x"><img data-src="/fallback.jpg"></picture><span class="olx-adcard__price">R$ 90.000</span></div>'''
    items = _fallback_parse_from_cards(html)
    assert items[0].thumbnail_url == "https://img.olx.com.br/lazy.webp"


def test_olx_placeholder_image_rejected():
    html = '<meta property="og:image" content="https://static.olx.com.br/placeholder.svg">'
    assert _extract_olx_detail_thumbnail(html, "https://www.olx.com.br/item/1") is None


def test_olx_detail_enrichment_respects_limit(monkeypatch):
    items = _fallback_parse_from_cards('''
    <div><a data-testid="adcard-link" href="https://www.olx.com.br/item/111111">A</a></div>
    <div><a data-testid="adcard-link" href="https://www.olx.com.br/item/222222">B</a></div>
    ''')
    calls = []
    def fake_fetch(url, **kwargs):
        calls.append(url)
        return '<meta property="og:image" content="https://img.olx.com.br/detail.jpg">'
    monkeypatch.setattr("app.scrapers.olx.fetch_html", fake_fetch)
    _enrich_missing_olx_thumbnails(items, ScrapeContext(source="olx"), limit=1)
    assert len(calls) == 1
    assert items[0].thumbnail_url == "https://img.olx.com.br/detail.jpg"
    assert items[1].thumbnail_url is None
