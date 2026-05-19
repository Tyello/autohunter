from decimal import Decimal
from pathlib import Path

from app.sources.auctions import sodre


def _read(name: str) -> str:
    return Path('tests/fixtures/auctions').joinpath(name).read_text(encoding='utf-8')


def test_allowlist_accepts_sodre_domains():
    assert sodre.validate_auction_source_url('https://www.sodresantoro.com.br/', sodre.ALLOWED_DOMAINS)
    assert sodre.validate_auction_source_url('https://sodresantoro.com.br/', sodre.ALLOWED_DOMAINS)
    assert not sodre.validate_auction_source_url('https://evil.example.com/', sodre.ALLOWED_DOMAINS)


def test_parse_listing_cards_and_fields():
    lots = sodre.parse_sodre_listing_html(_read('sodre_listing_with_cards.html'), limit=10)
    assert len(lots) == 3
    first, second, third = lots
    assert first.external_id == '101'
    assert first.title == 'Honda CG 160 FAN - 2020'
    assert first.url == 'https://www.sodresantoro.com.br/lote/honda-cg-160-fan-2020-101'
    assert first.item_type == 'motorcycle'
    assert second.item_type == 'car'
    assert third.item_type == 'truck'
    assert first.make == 'Honda'
    assert first.year == 2020
    assert first.city == 'São Paulo'
    assert first.state == 'SP'
    assert second.city == 'Guarulhos'
    assert second.state == 'SP'
    assert third.city == 'Curitiba'
    assert third.state == 'PR'
    assert first.status == 'open'
    assert second.status == 'live'
    assert third.status == 'scheduled'
    assert first.initial_bid == Decimal('8500.00')
    assert first.current_bid == Decimal('9200.00')
    assert second.current_bid == Decimal('132000.00')
    assert first.auction_end_at is not None
    assert third.auction_start_at is not None
    assert first.lot_number == '101'
    assert second.lot_number == '45'
    assert isinstance(first.extras, dict)
    assert first.extras['raw_status'] == 'Aberto'
    assert first.extras['raw_location'] == 'São Paulo/SP'


def test_fetch_empty_sets_reason(monkeypatch):
    html = _read('sodre_empty_listing.html')

    class _Resp:
        text = html

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, _url):
            return _Resp()

    monkeypatch.setattr(sodre.httpx, 'Client', _Client)
    lots = sodre.fetch_sodre_lots(limit=10)
    assert lots == []
    assert sodre.get_last_reason() == 'no_public_lot_cards_found'


def test_parse_anchor_fallback_without_known_classes_and_deduplicate():
    lots = sodre.parse_sodre_listing_html(_read('sodre_listing_anchor_fallback.html'), limit=10)
    assert len(lots) == 1
    lot = lots[0]
    assert lot.title == 'Honda CG 160 FAN - 2020'
    assert lot.url == 'https://www.sodresantoro.com.br/lote/honda-cg-160-fan-2020-12345'
    assert lot.external_id == '12345'
    assert lot.item_type == 'motorcycle'
    assert lot.city == 'São Paulo'
    assert lot.state == 'SP'
    assert lot.status == 'open'
    assert lot.current_bid == Decimal('9200.00')
    assert lot.auction_end_at is not None
    assert lot.lot_number == '101'


def test_fetch_empty_listing_with_js_signals_sets_requires_js_reason(monkeypatch):
    html = '<html><body><div id="react-root"></div><script>window.__NEXT_DATA__={}</script></body></html>'

    class _Resp:
        text = html

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, _url):
            return _Resp()

    monkeypatch.setattr(sodre.httpx, 'Client', _Client)
    lots = sodre.fetch_sodre_lots(limit=10)
    assert lots == []
    assert sodre.get_last_reason() == 'requires_js_or_internal_endpoint'


def test_fetch_403_sets_forbidden_reason(monkeypatch):
    class _Resp:
        status_code = 403
        text = ""

        def raise_for_status(self):
            raise AssertionError("should not raise for 403 controlled reason")

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, _url):
            return _Resp()

    monkeypatch.setattr(sodre.httpx, "Client", _Client)
    lots = sodre.fetch_sodre_lots(limit=10)
    assert lots == []
    assert sodre.get_last_reason() == "forbidden_403"


def test_sodre_detail_url_poc_parse():
    url = 'https://leilao.sodresantoro.com.br/leilao/28528/lote/2760648/'
    lot = sodre.parse_sodre_detail_html(_read('sodre/detail_lote_2760648.html'), url)
    assert lot.external_id == '2760648'
    assert lot.extras and lot.extras.get('auction_id') == '28528'
    assert lot.title
    assert lot.initial_bid == Decimal('12000.00')
