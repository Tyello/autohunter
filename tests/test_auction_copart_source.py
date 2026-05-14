from decimal import Decimal
from pathlib import Path

from app.sources.auctions import copart


FIXTURE = Path("tests/fixtures/auctions/copart_vehicle_finder.html")
FIXTURE_WITH_CARDS = Path("tests/fixtures/auctions/copart_vehicle_finder_with_cards.html")


def test_allowlist_accepts_copart_domains():
    assert copart.validate_auction_source_url("https://www.copart.com.br/vehicleFinder", copart.ALLOWED_DOMAINS)
    assert copart.validate_auction_source_url("https://copart.com.br/vehicleFinder", copart.ALLOWED_DOMAINS)


def test_allowlist_rejects_suspicious_domain():
    assert not copart.validate_auction_source_url("https://evil-copart.com.br", copart.ALLOWED_DOMAINS)


def test_parse_helpers():
    assert copart.parse_money_br("R$ 12.345,67") == Decimal("12345.67")
    assert copart.parse_int_br("1.234") == 1234
    assert copart.normalize_item_type("Automóveis") == "car"
    assert copart.normalize_item_type("Motos") == "motorcycle"


def test_fixture_without_cards_returns_empty_with_reason(monkeypatch):
    html = FIXTURE.read_text(encoding="utf-8")

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

    monkeypatch.setattr(copart.httpx, "Client", FakeClient)
    lots = copart.fetch_copart_lots(limit=5)
    assert lots == []
    assert copart.get_last_reason() == "requires_js_or_internal_endpoint"


def test_fixture_with_static_card_extracts_normalized_lot(monkeypatch):
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

    monkeypatch.setattr(copart.httpx, "Client", FakeClient)
    lots = copart.fetch_copart_lots(limit=5)
    assert len(lots) == 1
    assert lots[0].title == "Honda CG 160 2021"
    assert lots[0].url == "https://www.copart.com.br/lot/LOT123"
    assert lots[0].item_type == "motorcycle"
    assert lots[0].year == 2021
    assert lots[0].state == "SP"
