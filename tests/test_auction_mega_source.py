from datetime import datetime, timezone
from decimal import Decimal

from pathlib import Path

from app.sources.auctions import mega


def _read(name: str) -> str:
    return Path("tests/fixtures/auctions") .joinpath(name).read_text(encoding="utf-8")


def test_allowlist_accept_and_reject():
    assert mega.validate_auction_source_url("https://www.megaleiloes.com.br/veiculos/motos", mega.ALLOWED_DOMAINS)
    assert mega.validate_auction_source_url("https://megaleiloes.com.br/veiculos/motos", mega.ALLOWED_DOMAINS)
    assert not mega.validate_auction_source_url("https://evil.example.com/veiculos/motos", mega.ALLOWED_DOMAINS)


def test_parse_mega_listing_fields():
    lots = mega.parse_mega_listing_html(_read("mega_motos_listing.html"), limit=10)
    assert len(lots) == 3
    first = lots[0]
    assert first.external_id == "J122570"
    assert first.title == "Moto Honda XLR 125 ES - 2001"
    assert first.url and "J122570" in first.url
    assert first.item_type == "motorcycle"
    assert first.make == "Honda"
    assert first.year == 2001
    assert first.location == "São Paulo, SP"
    assert first.city == "São Paulo"
    assert first.state == "SP"
    assert first.status == "live"
    assert first.lot_number == "1"
    assert first.auction_start_at is not None
    assert first.auction_end_at is not None
    assert first.initial_bid is not None and str(first.initial_bid) == "6215.00"
    assert first.extras["second_praca_value"] == "3729.00"

    assert isinstance(first.extras["first_praca_at"], str)
    assert isinstance(first.extras["first_praca_value"], str)
    assert isinstance(first.extras["second_praca_at"], str)
    assert isinstance(first.extras["second_praca_value"], str)
    assert not isinstance(first.extras["first_praca_at"], datetime)
    assert not isinstance(first.extras["first_praca_value"], Decimal)

    second = lots[1]
    assert second.status == "scheduled"

    third = lots[2]
    assert third.location == "Não Informando, NI"
    assert third.city is None
    assert third.state is None


def test_fetch_empty_sets_reason(monkeypatch):
    class _Resp:
        text = _read("mega_empty_listing.html")
        def raise_for_status(self):
            return None
    class _Client:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def get(self, _url):
            return _Resp()

    monkeypatch.setattr(mega.httpx, "Client", lambda **kwargs: _Client())
    lots = mega.fetch_mega_lots(limit=5)
    assert lots == []
    assert mega.get_last_reason() == "no_public_lot_cards_found"

def test_parse_mega_ignores_dash_url_and_infers_title_from_slug():
    html = """
    <article class=\"card\">
      <a href=\"-\">Sem link</a><h3>Sem título</h3><span>J123456</span>
    </article>
    <article class=\"card\">
      <a href=\"/lote/moto-honda-cg-160-start-2022-J123457\">ver</a><span>J123457</span>
    </article>
    """
    lots = mega.parse_mega_listing_html(html, limit=10)
    assert len(lots) == 1
    assert lots[0].url and lots[0].url != "-"
    assert lots[0].title is not None

def test_parse_mega_fallback_alt_slug_absolute_url_and_external_id():
    html = """
    <article class="card">
      <a href='/lotes/touareg-v8-162758'><img alt='Volkswagen Touareg V8 2008' src='x.jpg'></a>
      <div>Local: Curitiba, PR</div>
      <div>1ª Praça: 15/05/2026 às 10:00 - R$ 45.000,00</div>
    </article>
    """
    lots = mega.parse_mega_listing_html(html, limit=5, listing_url='https://www.megaleiloes.com.br/veiculos')
    assert len(lots) == 1
    lot = lots[0]
    assert lot.title == 'Volkswagen Touareg V8 2008'
    assert lot.url == 'https://www.megaleiloes.com.br/lotes/touareg-v8-162758'
    assert lot.external_id == '162758'


def test_mega_helpers_item_type_and_compact_year():
    assert mega.infer_mega_item_type("Carro Hyundai I30 20 20092010 J122572", "https://www.megaleiloes.com.br/veiculos/carros/lote/x") == "car"
    assert mega.infer_mega_item_type("Direitos Sobre Carro Renault Sandero Expr 16 2015", "https://www.megaleiloes.com.br/veiculos/carros/sp/santos/lote-j123123") == "car"
    assert mega.infer_mega_item_type("Leiloes Judiciais", "https://www.megaleiloes.com.br/leiloes-judiciais") != "motorcycle"
    assert mega.parse_mega_compact_year("Carro Hyundai I30 20 20092010 J122572") == 2009
    assert mega.parse_mega_compact_year("Carro Volkswagen Gol 10 20122013 J123409") == 2012


def test_mega_listing_rejects_generic_pages_and_missing_j_id():
    html = """
    <article class="card"><a href="/leiloes-judiciais">ver</a><h3>Leiloes Judiciais</h3></article>
    <article class="card"><a href="/veiculos/carros/sp/sao-paulo/carro-hyundai">ver</a><h3>Carro Hyundai</h3></article>
    """
    lots = mega.parse_mega_listing_html(html, limit=10, listing_url="https://www.megaleiloes.com.br/veiculos/carros")
    assert lots == []


def test_mega_detail_kombi_fixture_extracts_minimum_fields():
    url = 'https://www.megaleiloes.com.br/veiculos/carros/sp/atibaia/veiculo-volkswagen-kombi-carat-16-mi-1999-j122290?utm_source=x&utm_medium=y'
    lot = mega.parse_mega_detail_html(_read('mega/detail_kombi.html'), url)
    assert lot.title == 'Volkswagen Kombi Carat 1.6 MI 1999'
    assert lot.item_type == 'car'
    assert lot.item_type != 'motorcycle'
    assert lot.year == 1999
    assert lot.state == 'SP'
    assert lot.city == 'Atibaia'
    assert lot.external_id == 'J122290'
    assert lot.thumbnail_url == "https://www.megaleiloes.com.br/img/kombi.jpg"


def test_mega_detail_extracts_bids_dates_and_status_conservatively():
    html = """
    <html><head><meta property="og:image" content="https://cdn.mega/lote.jpg"></head><body>
    <div>Status: encerrado</div>
    <div>Data do Leilão: 21/05/2026 às 10:00</div>
    <div>Encerramento: 22/05/2026 às 16:30</div>
    <div>Lance Inicial: R$ 25.000,00</div>
    <div>Lance Atual: R$ 30.000,00</div>
    </body></html>
    """
    lot = mega.parse_mega_detail_html(html, "https://www.megaleiloes.com.br/veiculos/carros/sp/atibaia/x-j100001")
    assert lot.initial_bid is not None and str(lot.initial_bid) == "25000.00"
    assert lot.current_bid is not None and str(lot.current_bid) == "30000.00"
    assert lot.auction_start_at == datetime(2026, 5, 21, 13, 0, tzinfo=timezone.utc)
    assert lot.auction_end_at == datetime(2026, 5, 22, 19, 30, tzinfo=timezone.utc)
    assert lot.status == "ended"


def test_mega_detail_datetime_parsing_variants_and_field_mapping():
    lot_space = mega.parse_mega_detail_html(
        "<div>Data do Leilão: 21/05/2026 10:00</div>",
        "https://www.megaleiloes.com.br/veiculos/carros/sp/atibaia/x-j100010",
    )
    assert lot_space.auction_start_at == datetime(2026, 5, 21, 13, 0, tzinfo=timezone.utc)
    assert lot_space.auction_end_at is None

    lot_as = mega.parse_mega_detail_html(
        "<div>Data do Leilão: 21/05/2026 às 10:00</div>",
        "https://www.megaleiloes.com.br/veiculos/carros/sp/atibaia/x-j100011",
    )
    assert lot_as.auction_start_at == datetime(2026, 5, 21, 13, 0, tzinfo=timezone.utc)
    assert lot_as.auction_end_at is None

    lot_dash = mega.parse_mega_detail_html(
        "<div>Encerramento: 22/05/2026 - 16:30</div>",
        "https://www.megaleiloes.com.br/veiculos/carros/sp/atibaia/x-j100012",
    )
    assert lot_dash.auction_start_at is None
    assert lot_dash.auction_end_at == datetime(2026, 5, 22, 19, 30, tzinfo=timezone.utc)

    lot_h = mega.parse_mega_detail_html(
        "<div>Encerramento: 22/05/2026 às 16h30</div>",
        "https://www.megaleiloes.com.br/veiculos/carros/sp/atibaia/x-j100013",
    )
    assert lot_h.auction_start_at is None
    assert lot_h.auction_end_at == datetime(2026, 5, 22, 19, 30, tzinfo=timezone.utc)


def test_mega_detail_online_generic_and_logo_banner_image_are_ignored():
    html = """
    <html><head>
      <meta property="og:image" content="https://cdn.mega/logo.png">
    </head><body>
      <div>Status: online</div>
      <img src="https://cdn.mega/banner-home.jpg" />
    </body></html>
    """
    lot = mega.parse_mega_detail_html(html, "https://www.megaleiloes.com.br/veiculos/carros/sp/atibaia/x-j100002")
    assert lot.status == "unknown"
    assert lot.thumbnail_url is None


def test_mega_detail_invalid_location_slug_is_not_populated():
    lot = mega.parse_mega_detail_html("<h1>Fiat Fiorino 2018</h1>", "https://www.megaleiloes.com.br/veiculos/carros/si/sem-informacao/x-j100003")
    assert lot.city is None
    assert lot.state is None
    assert lot.location is None


def test_mega_detail_valid_location_slug_is_populated():
    lot = mega.parse_mega_detail_html("<h1>Audi Q3 2016</h1>", "https://www.megaleiloes.com.br/veiculos/carros/sp/sao-bernardo-do-campo/x-j100004")
    assert lot.city == "Sao Bernardo Do Campo"
    assert lot.state == "SP"


def test_audit_mega_persisted_lot_generic_page():
    lot = type("Lot", (), {"url": "https://www.megaleiloes.com.br/leiloes-judiciais", "item_type": "motorcycle", "city": None, "state": None, "location": None})()
    out = mega.audit_mega_persisted_lot(lot)
    assert "generic_page" in out["issues"]
    assert out["suggested_updates"]["status"] == "invalid"
    assert out["suggested_updates"]["item_type"] == "other"


def test_audit_mega_persisted_lot_item_type_mismatch_and_invalid_location():
    lot = type("Lot", (), {"url": "https://www.megaleiloes.com.br/veiculos/carros/si/sem-informacao/direitos-j121066", "item_type": "motorcycle", "city": "SI", "state": "SI", "location": "Sem informação, SI"})()
    out = mega.audit_mega_persisted_lot(lot)
    assert "item_type_mismatch" in out["issues"]
    assert "invalid_location" in out["issues"]
    assert out["suggested_updates"]["item_type"] == "car"
    assert out["suggested_updates"]["city"] is None
    assert out["suggested_updates"]["state"] is None
    assert out["suggested_updates"]["location"] is None


def test_audit_mega_persisted_lot_valid_car_ok():
    lot = type("Lot", (), {"url": "https://www.megaleiloes.com.br/veiculos/carros/sp/santos/carro-j121066", "item_type": "car", "city": "Santos", "state": "SP", "location": "Santos, SP"})()
    out = mega.audit_mega_persisted_lot(lot)
    assert out["ok"] is True
    assert out["issues"] == []
