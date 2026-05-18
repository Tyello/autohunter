from datetime import datetime
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
    assert first.status == "open"
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
