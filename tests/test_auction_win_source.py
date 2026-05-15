from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.sources.auctions import win


def _read(name: str) -> str:
    return Path("tests/fixtures/auctions").joinpath(name).read_text(encoding="utf-8")


def test_allowlist_accept_and_reject():
    assert win.validate_auction_source_url("https://winleiloes.com.br/", win.ALLOWED_DOMAINS)
    assert win.validate_auction_source_url("https://www.winleiloes.com.br/", win.ALLOWED_DOMAINS)
    assert not win.validate_auction_source_url("https://evil.example.com/", win.ALLOWED_DOMAINS)


def test_parse_win_listing_fields():
    lots = win.parse_win_listing_html(_read("win_home_listing.html"), limit=10)
    assert len(lots) == 4
    first = lots[0]
    assert first.initial_bid == Decimal("253993.84")
    assert first.current_bid is None
    assert first.city == "Irani"
    assert first.state == "SC"

    live = lots[2]
    assert live.status == "live"
    assert live.auction_start_at == datetime(2026, 5, 14, 14, 0, tzinfo=timezone.utc)

    scheduled = lots[3]
    assert scheduled.status == "scheduled"
    assert scheduled.auction_start_at == datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc)

    assert all(not isinstance(v, Decimal) for lot in lots for v in lot.extras.values())
    assert all(not hasattr(v, "tzinfo") for lot in lots for v in lot.extras.values())


def test_fetch_empty_sets_reason(monkeypatch):
    class _Resp:
        text = _read("win_empty_listing.html")
        def raise_for_status(self):
            return None

    class _Client:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def get(self, _url):
            return _Resp()

    monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
    lots = win.fetch_win_lots(limit=5)
    assert lots == []
    assert win.get_last_reason() == "no_public_lot_cards_found"
