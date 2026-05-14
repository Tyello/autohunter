from decimal import Decimal
from pathlib import Path

from app.sources.auctions import vip

FIXTURE_WITH_CARDS = Path("tests/fixtures/auctions/vip_listing_with_cards.html")
FIXTURE_NO_CARDS = Path("tests/fixtures/auctions/vip_listing_without_cards.html")


def test_allowlist_accepts_vip_domains():
    assert vip.validate_auction_source_url("https://www.vipleiloes.com.br/", vip.ALLOWED_DOMAINS)
    assert vip.validate_auction_source_url("https://www2.vipleiloes.com.br/lista", vip.ALLOWED_DOMAINS)


def test_allowlist_rejects_blocked_or_outside_domains():
    assert not vip.validate_auction_source_url("https://vipleiloes.club/", vip.ALLOWED_DOMAINS)
    assert not vip.validate_auction_source_url("https://example.com/", vip.ALLOWED_DOMAINS)


def test_parser_extracts_positive_card(monkeypatch):
    html = FIXTURE_WITH_CARDS.read_text(encoding="utf-8")

    class FakeResp:
        text = html

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            return FakeResp()

    monkeypatch.setattr(vip.httpx, "Client", FakeClient)
    lots = vip.fetch_vip_lots(limit=5)
    assert len(lots) == 1
    lot = lots[0]
    assert lot.title == "Honda Civic 2019"
    assert lot.initial_bid == Decimal("38000.00")
    assert lot.current_bid == Decimal("45000.00")
    assert lot.lot_number == "123"
    assert lot.state == "SP"
    assert lot.total_bids == 7
    assert lot.item_type == "car"
    assert lot.auction_start_at is not None


def test_fallback_without_cards_returns_reason(monkeypatch):
    html = FIXTURE_NO_CARDS.read_text(encoding="utf-8")

    class FakeResp:
        text = html

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            return FakeResp()

    monkeypatch.setattr(vip.httpx, "Client", FakeClient)
    lots = vip.fetch_vip_lots(limit=5)
    assert lots == []
    assert vip.get_last_reason() == "no_public_lot_cards_found"
