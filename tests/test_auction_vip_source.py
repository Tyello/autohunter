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


def test_parser_groups_duplicate_blocks_by_url(monkeypatch):
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

    assert len(lots) == 2
    by_id = {lot.external_id: lot for lot in lots}
    assert set(by_id) == {"157925", "156375"}

    first = by_id["157925"]
    assert first.title == "DUCATO MAXICARGO - 2010/2011"
    assert first.status == "live"
    assert first.make == "Fiat"
    assert first.mileage_km == 180000
    assert first.year == 2010
    assert first.item_type == "car"
    assert first.extras.get("plate_final") == "7"

    second = by_id["156375"]
    assert second.title == "SANDERO EXPR 10 - 2018/2019"
    assert second.status == "live"
    assert second.make == "Renault"
    assert second.mileage_km == 95000
    assert second.year == 2018
    assert second.item_type == "car"


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
