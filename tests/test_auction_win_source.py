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


def test_win_default_vehicle_listing_url_and_external_id_parser():
    assert '/lotes/veiculo' in win.DEFAULT_LISTING_URL
    assert 'categoria_id=8' in win.DEFAULT_LISTING_URL
    assert win.parse_win_external_id_from_url('https://www.winleiloes.com.br/item/4042/detalhes?page=1') == '4042'


def test_win_listing_detail_href_without_title_creates_minimal_lot():
    html = '<div><a href="/item/4042/detalhes?page=1">detalhes</a></div>'
    lots = win.parse_win_listing_html(html, limit=5)
    assert len(lots) == 1
    assert lots[0].external_id == "4042"
    assert lots[0].title is None
    assert lots[0].item_type == "other"
    assert lots[0].url.endswith("/item/4042/detalhes")


def test_win_listing_js_string_detail_url_and_deduplicate():
    html = """
    <script>
      const x="/item/4042/detalhes?page=1";
      const y="https://www.winleiloes.com.br/item/4042/detalhes?page=1";
    </script>
    """
    lots = win.parse_win_listing_html(html, limit=10)
    assert len(lots) == 1
    assert lots[0].external_id == "4042"


def test_win_no_detail_urls_keeps_requires_endpoint_reason(monkeypatch):
    class _Resp:
        text = '<html><script>window.__NEXT_DATA__={}</script><title>Busca de Veículos</title></html>'
        status_code = 200
        url = "https://www.winleiloes.com.br/lotes/veiculo"
        headers = {"content-type": "text/html"}
        def raise_for_status(self): return None
    class _Client:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, _url): return _Resp()
    monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
    out = win.fetch_win_lots(limit=5)
    assert out == []
    assert win.get_last_reason() == "no_detail_urls_found_requires_endpoint_study"


def test_win_vehicle_listing_fixture_and_detail_parsing(monkeypatch):
    listing_html = _read('win/listing_vehicle.html')
    detail_html = _read('win/detail_item_4042.html')

    class _Resp:
        def __init__(self, text): self.text=text
        def raise_for_status(self): return None
    class _Client:
        def __enter__(self): return self
        def __exit__(self,*_): return False
        def get(self,url):
            if 'item/4042' in url: return _Resp(detail_html)
            return _Resp(listing_html)

    monkeypatch.setattr(win.httpx, 'Client', lambda **kwargs: _Client())
    lots = win.fetch_win_lots(limit=5, enrich=True)
    assert lots
    lot = lots[0]
    assert lot.external_id == '4042'
    assert lot.item_type == 'car'
    assert lot.year == 2016
    assert lot.initial_bid == Decimal('66500.00')
    assert lot.current_bid == Decimal('67000.00')
    assert lot.city == 'São Paulo'
    assert lot.state == 'SP'
    assert lot.location == 'São Paulo/SP'
    assert lot.thumbnail_url and '4042.jpg' in lot.thumbnail_url
    assert '?page=1' not in (lot.url or '')


def test_win_enrich_extracts_end_date_status_and_current_bid(monkeypatch):
    listing_html = '<article class="card"><a href="/item/4086/detalhes">item</a></article>'
    detail_html = _read("win/detail_item_4086.html")

    class _Resp:
        def __init__(self, text): self.text = text
        def raise_for_status(self): return None
    class _Client:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, url): return _Resp(detail_html if "/item/4086/detalhes" in url else listing_html)

    monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
    lot = win.fetch_win_lots(limit=1, enrich=True)[0]
    assert lot.status == "live"
    assert lot.auction_end_at == datetime(2026, 5, 22, 14, 30, tzinfo=timezone.utc)
    assert lot.current_bid == Decimal("98700.00")


def test_win_enrich_extracts_ended_status_and_no_fake_current_bid(monkeypatch):
    listing_html = '<article class="card"><a href="/item/4084/detalhes">item</a></article>'
    detail_html = _read("win/detail_item_4084.html")

    class _Resp:
        def __init__(self, text): self.text = text
        def raise_for_status(self): return None
    class _Client:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, url): return _Resp(detail_html if "/item/4084/detalhes" in url else listing_html)

    monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
    lot = win.fetch_win_lots(limit=1, enrich=True)[0]
    assert lot.status == "ended"
    assert lot.auction_end_at == datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc)
    assert lot.current_bid == Decimal("36500.00")


def test_win_enrich_extracts_start_date_and_keeps_current_bid_none_when_only_initial(monkeypatch):
    listing_html = '<article class="card"><a href="/item/4085/detalhes">item</a></article>'
    detail_html = _read("win/detail_item_4085.html")

    class _Resp:
        def __init__(self, text): self.text = text
        def raise_for_status(self): return None
    class _Client:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, url): return _Resp(detail_html if "/item/4085/detalhes" in url else listing_html)

    monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
    lot = win.fetch_win_lots(limit=1, enrich=True)[0]
    assert lot.status == "live"
    assert lot.auction_start_at == datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc)
    assert lot.auction_end_at is None
    assert lot.initial_bid == Decimal("54000.00")
    assert lot.current_bid is None


def test_win_enrich_without_clear_end_date_keeps_none(monkeypatch):
    listing_html = '<article class="card"><a href="/item/4077/detalhes">item</a></article>'
    detail_html = _read("win/detail_item_4077.html")

    class _Resp:
        def __init__(self, text): self.text = text
        def raise_for_status(self): return None
    class _Client:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, url): return _Resp(detail_html if "/item/4077/detalhes" in url else listing_html)

    monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
    lot = win.fetch_win_lots(limit=1, enrich=True)[0]
    assert lot.status == "scheduled"
    assert lot.auction_end_at is None


def test_win_status_requires_explicit_label_not_generic_online_word(monkeypatch):
    listing_html = '<article class="card"><a href="/item/4999/detalhes">item</a></article>'
    detail_html = """
    <html><head><title>Leilão online de veículos</title></head>
    <body><h1>Lote 4999</h1><footer>Plataforma de leilões online</footer></body></html>
    """

    class _Resp:
        def __init__(self, text): self.text = text
        def raise_for_status(self): return None
    class _Client:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, url): return _Resp(detail_html if "/item/4999/detalhes" in url else listing_html)

    monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
    lot = win.fetch_win_lots(limit=1, enrich=True)[0]
    assert lot.status == "unknown"


def test_win_status_labeled_mappings(monkeypatch):
    listing_html = '<article class="card"><a href="/item/5000/detalhes">item</a></article>'
    cases = [
        ("<div>Status: Em andamento</div>", "live"),
        ("<div>Situação: Encerrado</div>", "ended"),
        ("<div>Situação: Em loteamento</div>", "scheduled"),
    ]

    class _Resp:
        def __init__(self, text): self.text = text
        def raise_for_status(self): return None
    for body, expected in cases:
        class _Client:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def get(self, url):
                if "/item/5000/detalhes" in url:
                    return _Resp(f"<html><body>{body}</body></html>")
                return _Resp(listing_html)
        monkeypatch.setattr(win.httpx, "Client", lambda **kwargs: _Client())
        lot = win.fetch_win_lots(limit=1, enrich=True)[0]
        assert lot.status == expected


def test_infer_win_item_type_vehicle_and_real_estate_priority():
    assert win.infer_win_item_type("Moto Honda CG 160 Fan 2021") == "motorcycle"
    assert win.infer_win_item_type("Honda Biz 125 2020") == "motorcycle"
    assert win.infer_win_item_type("Honda Titan 160") == "motorcycle"
    assert win.infer_win_item_type("Caminhão Ford Cargo 2429") == "truck"
    assert win.infer_win_item_type("Mercedes-Benz Atego 2426") == "truck"
    assert win.infer_win_item_type("TOYOTA/HILUX CDLOWM4FD - 2016 - 2017 - DIESEL") == "car"
    assert win.infer_win_item_type("Imóvel Comercial em Altos") == "real_estate"


def test_win_html_real_estate_noise_does_not_override_vehicle_title(monkeypatch):
    listing_html = '<article class="card"><a href="/item/4042/detalhes">item</a><h3>TOYOTA/HILUX CDLOWM4FD - 2016 - 2017 - DIESEL</h3></article>'
    detail_html = '<html><body><h1>TOYOTA/HILUX CDLOWM4FD - 2016 - 2017 - DIESEL</h1><footer>imóvel terreno casa</footer></body></html>'

    class _Resp:
        def __init__(self, text): self.text=text
        def raise_for_status(self): return None
    class _Client:
        def __enter__(self): return self
        def __exit__(self,*_): return False
        def get(self,url): return _Resp(detail_html if '/item/4042/detalhes' in url else listing_html)

    monkeypatch.setattr(win.httpx, 'Client', lambda **kwargs: _Client())
    lot = win.fetch_win_lots(limit=1, enrich=True)[0]
    assert lot.item_type == 'car'


def test_parse_win_location_rejects_com_pi():
    assert win.parse_win_location('com / PI') == (None, None, None)


def test_parse_win_location_rejects_brand_as_city():
    assert win.parse_win_location("CAOA CHERY / CE") == (None, None, None)


def test_parse_win_location_rejects_title_like_brand_with_uf():
    assert win.parse_win_location("TOYOTA/HILUX / SP") == (None, None, None)


def test_parse_win_location_accepts_reliable_city_uf():
    assert win.parse_win_location("Curitiba / PR") == ("Curitiba", "PR", "Curitiba/PR")


def test_is_reliable_win_location_helper_rules():
    assert win.is_reliable_win_location("Curitiba", "PR", "Curitiba/PR") is True
    assert win.is_reliable_win_location("CAOA CHERY", "CE", "CAOA CHERY/CE") is False
    assert win.is_reliable_win_location("www", "SP", "www/SP") is False
    assert win.is_reliable_win_location("TOYOTA/HILUX", "SP", "TOYOTA/HILUX/SP") is False
