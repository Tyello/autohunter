from decimal import Decimal

from app.sources.auctions.base import NormalizedAuctionLot
from app.sources.auctions.quality import validate_normalized_auction_lot_candidate


def _lot(**kwargs):
    data = {
        "source": "vip_auctions",
        "external_id": "x1",
        "title": "Honda CG 160",
        "url": "https://example.com/item/1",
        "year": 2020,
    }
    data.update(kwargs)
    return NormalizedAuctionLot(**data)


def test_missing_url_rejected():
    assert validate_normalized_auction_lot_candidate(_lot(url=None)).reason == "invalid_url"


def test_dash_url_rejected():
    assert validate_normalized_auction_lot_candidate(_lot(url="-")).reason == "invalid_url"


def test_missing_title_rejected():
    assert validate_normalized_auction_lot_candidate(_lot(title=None)).reason == "missing_title"


def test_sem_titulo_rejected():
    assert validate_normalized_auction_lot_candidate(_lot(title="Sem título")).reason == "invalid_title"


def test_institutional_title_rejected():
    assert validate_normalized_auction_lot_candidate(_lot(title="Navegue pelas categorias")).reason == "institutional_title"


def test_login_url_rejected():
    assert validate_normalized_auction_lot_candidate(_lot(url="https://x.com/login")).reason == "institutional_url"


def test_categorias_url_rejected():
    assert validate_normalized_auction_lot_candidate(_lot(url="https://x.com/categorias/motos")).reason == "institutional_url"


def test_title_url_year_accepted():
    assert validate_normalized_auction_lot_candidate(_lot(year=2021)).ok


def test_title_url_current_bid_accepted():
    assert validate_normalized_auction_lot_candidate(_lot(year=None, current_bid=Decimal("10"))).ok


def test_without_useful_signals_rejected():
    out = validate_normalized_auction_lot_candidate(_lot(year=None, current_bid=None, initial_bid=None, auction_end_at=None, city=None, state=None, mileage_km=None, lot_number=None))
    assert out.reason == "insufficient_lot_signals"


def test_canais_and_sobre_nos_rejected():
    assert validate_normalized_auction_lot_candidate(_lot(source="superbid_auctions", title="Canais", year=None)).reason == "institutional_title"
    assert validate_normalized_auction_lot_candidate(_lot(source="superbid_auctions", title="Sobre Nós", year=None)).reason == "institutional_title"


def test_lance_inicial_title_rejected_with_specific_reason():
    out = validate_normalized_auction_lot_candidate(_lot(source="win_auctions", title="Lance Inicial: R$600.000,00", year=None))
    assert out.reason == "title_is_bid_label"


def test_superbid_url_todos_eventos_pdf_blog_rejected():
    assert validate_normalized_auction_lot_candidate(_lot(source="superbid_auctions", url="https://www.superbid.net/todos-eventos", year=2020)).reason == "institutional_url"
    assert validate_normalized_auction_lot_candidate(_lot(source="superbid_auctions", url="https://blog.superbid.net/materia", year=2020)).reason == "pdf_or_blog_url"
    assert validate_normalized_auction_lot_candidate(_lot(source="superbid_auctions", url="https://www.superbid.net/files/manual.pdf", year=2020)).reason == "pdf_or_blog_url"


def test_city_state_only_not_enough_for_win_and_superbid():
    win_out = validate_normalized_auction_lot_candidate(_lot(source="win_auctions", year=None, current_bid=None, initial_bid=None, auction_end_at=None, lot_number=None, city="São Paulo", state="SP"))
    sb_out = validate_normalized_auction_lot_candidate(_lot(source="superbid_auctions", year=None, current_bid=None, initial_bid=None, auction_end_at=None, lot_number=None, city="São Paulo", state="SP"))
    assert win_out.reason == "insufficient_lot_signals"
    assert sb_out.reason == "insufficient_lot_signals"
