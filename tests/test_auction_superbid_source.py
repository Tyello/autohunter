import json
from pathlib import Path

from app.sources.auctions import superbid


def _fixture(name: str) -> str:
    return Path("tests/fixtures/auctions") .joinpath(name).read_text(encoding="utf-8")


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


def test_anchor_fallback_and_dedupe_and_status_mapping():
    html = _fixture("superbid_anchor_fallback.html") + _fixture("superbid_anchor_fallback.html")
    lots = superbid.parse_superbid_listing_html(html, listing_url="https://www.superbid.net/")
    assert len(lots) == 2
    statuses = {x.status for x in lots}
    assert "post_auction" in statuses or "buy_now" in statuses
    assert "ended" in statuses


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
