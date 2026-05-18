from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.sources.auctions import win
from app.sources.auctions.quality import validate_normalized_auction_lot_candidate


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

def test_win_blocks_institutional_and_parses_initial_bid():
    html = """
    <article class=\"card\"><a href=\"/licitante/cadastro/login\">Login</a></article>
    <article class=\"card\"><a href=\"/lotes/search\">search</a></article>
    <article class=\"card\"><a href=\"/leiloes/venda-direta\">venda direta</a></article>
    <article class=\"card\"><a href=\"/item/3739/detalhes\">item</a><h3>Lance Inicial: R$600.000,00</h3><div>Lance Inicial: R$ 600.000,00</div></article>
    """
    lots = win.parse_win_listing_html(html, limit=10)
    assert len(lots) == 1
    assert lots[0].title is None
    assert lots[0].initial_bid == Decimal('600000.00')
    assert validate_normalized_auction_lot_candidate(lots[0]).reason == "missing_title"


def test_win_only_accepts_item_detalhes_urls():
    html = """
    <article class="card"><a href="/leilao/123/lotes">Lotes</a><h3>Honda CG 160 2020</h3></article>
    <article class="card"><a href="/item/3739/detalhes">Detalhes</a><h3>Honda CG 160 2020</h3><div>Lance Inicial: R$ 12.000,00</div></article>
    """
    lots = win.parse_win_listing_html(html, limit=10)
    assert len(lots) == 1
    assert lots[0].url.endswith("/item/3739/detalhes")

def test_win_fallback_alt_and_external_id_from_url():
    html = """
    <article class="card">
      <a href='/item/placa-abc'><img alt='Chevrolet Onix 2018' src='x.jpg'></a>
      <div>Lance Inicial: R$ 25.000,00</div>
      <div>Curitiba/PR</div>
    </article>
    """
    lots = win.parse_win_listing_html(html, limit=5, listing_url='https://winleiloes.com.br/')
    assert len(lots) == 1
    lot = lots[0]
    assert lot.title == 'Chevrolet Onix 2018'
    assert lot.external_id == 'placa-abc'


def test_win_enrich_detail_updates_fields_and_returns_dataclass(monkeypatch):
    listing_html = '<article class="card"><a href="/item/3739/detalhes">item</a><h3></h3></article>'
    detail_html = """
    <html><head><meta property="og:title" content="Carro Hyundai HB20 2019"></head>
    <body><div>Lance Inicial: R$ 45.000,00</div><div>Em Andamento</div><div>Curitiba/PR</div></body></html>
    """

    class _Resp:
        def __init__(self, text):
            self.text = text
        def raise_for_status(self):
            return None

    class _Client:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def get(self, url):
            if '/item/3739/detalhes' in url:
                return _Resp(detail_html)
            return _Resp(listing_html)

    monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
    lot = win.fetch_win_lots(limit=1, enrich=True)[0]
    assert isinstance(lot, win.NormalizedAuctionLot)
    assert lot.title == "Carro Hyundai HB20 2019"
    assert lot.initial_bid == Decimal("45000.00")
    assert lot.year == 2019
    assert lot.item_type == "car"


def test_win_source_does_not_use_model_copy_api():
    src = Path("app/sources/auctions/win.py").read_text(encoding="utf-8")
    assert "model_copy(" not in src


def test_win_enrich_real_estate_detail_does_not_fill_year_from_html(monkeypatch):
    listing_html = '<article class="card"><a href="/item/2090/detalhes">item</a><h3>Apartamento com garagem</h3></article>'
    detail_html = """
    <html><head><meta property="og:title" content="Apartamento Centro"></head>
    <body><div>Edital 2025</div><div>Matrícula 2090</div><div>Lance Inicial: R$ 600.000,00</div></body></html>
    """

    class _Resp:
        def __init__(self, text):
            self.text = text
        def raise_for_status(self):
            return None

    class _Client:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def get(self, url):
            if "/item/2090/detalhes" in url:
                return _Resp(detail_html)
            return _Resp(listing_html)

    monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
    lot = win.fetch_win_lots(limit=1, enrich=True)[0]
    assert lot.item_type == "real_estate"
    assert lot.year is None


def test_win_enrich_vehicle_detail_still_fills_year(monkeypatch):
    listing_html = '<article class="card"><a href="/item/2020/detalhes">item</a><h3>Honda Civic</h3></article>'
    detail_html = """
    <html><head><meta property="og:title" content="Carro Honda Civic"></head>
    <body><div>Carro</div><div>Ano Modelo 2020</div><div>Lance Inicial: R$ 70.000,00</div></body></html>
    """

    class _Resp:
        def __init__(self, text):
            self.text = text
        def raise_for_status(self):
            return None

    class _Client:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def get(self, url):
            if "/item/2020/detalhes" in url:
                return _Resp(detail_html)
            return _Resp(listing_html)

    monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
    lot = win.fetch_win_lots(limit=1, enrich=True)[0]
    assert lot.item_type == "car"
    assert lot.year == 2020
