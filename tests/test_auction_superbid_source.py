import json
from decimal import Decimal
from pathlib import Path

from app.sources.auctions import superbid


def _fixture(name: str) -> str:
    return Path("tests/fixtures/auctions").joinpath(name).read_text(encoding="utf-8")


def test_allowlist_accept_and_reject():
    assert superbid._valid_source_url("https://www.superbid.net/")
    assert superbid._valid_source_url("https://superbid.net/")
    assert superbid._valid_source_url("https://exchange.superbid.net/")
    assert not superbid._valid_source_url("https://example.com/")


def test_parse_listing_cards_extracts_fields_and_mappings():
    lots = superbid.parse_superbid_listing_html(_fixture("superbid_listing_with_cards.html"), listing_url="https://www.superbid.net/")
    assert len(lots) == 4
    l1, l2, l3, l4 = lots
    assert l1.external_id and l1.title == "Honda CG 160 FAN - 2020"
    assert l1.url.startswith("https://www.superbid.net/")
    assert l1.item_type == "motorcycle"
    assert l1.make == "Honda" and l1.year == 2020
    assert l1.city == "São Paulo" and l1.state == "SP" and l1.location == "São Paulo/SP"
    assert l1.status == "open"
    assert str(l1.initial_bid) == "8500.00" and str(l1.current_bid) == "9200.00"
    assert l1.auction_end_at is not None and l1.lot_number == "101"

    assert l2.item_type == "car" and l2.status == "live"
    assert l3.item_type == "truck" and l3.auction_start_at is not None
    assert l4.item_type == "heavy_machinery" and l4.status == "quote"

    assert l4.thumbnail_url and "logo" not in l4.thumbnail_url.lower()
    json.dumps(l1.extras)


def test_anchor_fallback_extracts_distant_data_and_dedupes_same_href():
    lots = superbid.parse_superbid_listing_html(_fixture("superbid_anchor_fallback.html"), listing_url="https://www.superbid.net/")
    assert len(lots) == 1
    lot = lots[0]
    assert lot.title == "Honda CG 160 FAN - 2020"
    assert lot.url == "https://www.superbid.net/eventos/honda-cg-160-fan-2020-98101"
    assert lot.external_id == "98101"
    assert lot.item_type == "motorcycle"
    assert lot.city == "São Paulo" and lot.state == "SP" and lot.location == "São Paulo/SP"
    assert lot.status == "open"
    assert lot.current_bid == Decimal("9200.00")
    assert lot.auction_end_at is not None
    assert lot.lot_number == "101"


def test_anchor_institutional_is_ignored():
    html = """
    <html><body>
      <a href='/login'>Login</a>
      <a href='/contato'>Contato</a>
      <a href='/minha-conta'>Minha conta</a>
      <a href='/termos'>Termos</a>
    </body></html>
    """
    lots = superbid.parse_superbid_listing_html(html, listing_url="https://www.superbid.net/")
    assert lots == []


def test_fetch_sets_reason_for_invalid_and_js(monkeypatch):
    assert superbid.fetch_superbid_lots(listing_url="https://invalid.example/") == []
    assert superbid.get_last_reason() == "invalid_source_url"

    class _Resp:
        text = _fixture("superbid_empty_listing.html")

        def raise_for_status(self):
            return None

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, _url):
            return _Resp()

    monkeypatch.setattr(superbid.httpx, "Client", lambda **kwargs: _Client())
    out = superbid.fetch_superbid_lots(listing_url="https://exchange.superbid.net/")
    assert out == []
    assert superbid.get_last_reason() in {"requires_js_or_internal_endpoint", "no_public_lot_cards_found"}
