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
