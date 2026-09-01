from __future__ import annotations

from app.models.source_config import SourceConfig
from app.services.auction_source_categories_service import (
    get_auction_allowed_item_types,
    is_auction_item_type_allowed,
    normalize_item_type,
)


def test_normalize_item_type_handles_aliases_and_case():
    assert normalize_item_type("Carros") == "car"
    assert normalize_item_type("MOTOS") == "motorcycle"
    assert normalize_item_type("caminhão") == "truck"


def test_normalize_item_type_returns_none_for_unknown():
    assert normalize_item_type("spaceship") is None


def test_normalize_item_type_returns_none_for_none_or_blank():
    assert normalize_item_type(None) is None
    assert normalize_item_type("   ") is None


def test_get_allowed_item_types_defaults_to_car_for_unknown_source(db):
    assert get_auction_allowed_item_types(db, "unknown_source") == {"car"}


def test_get_allowed_item_types_defaults_to_car_when_no_config_row(db):
    assert get_auction_allowed_item_types(db, "mega_auctions") == {"car"}


def test_get_allowed_item_types_reads_extra_config(db):
    cfg = SourceConfig(source="mega_auctions", source_type="auction", extra={"allowed_item_types": ["car", "moto"]})
    db.add(cfg)
    db.commit()

    result = get_auction_allowed_item_types(db, "mega")
    assert result == {"car", "motorcycle"}


def test_get_allowed_item_types_falls_back_when_extra_is_empty(db):
    cfg = SourceConfig(source="mega_auctions", source_type="auction", extra={"allowed_item_types": []})
    db.add(cfg)
    db.commit()

    assert get_auction_allowed_item_types(db, "mega") == {"car"}


def test_is_auction_item_type_allowed_true_for_default_car(db):
    assert is_auction_item_type_allowed(db, "mega_auctions", "car") is True


def test_is_auction_item_type_allowed_false_for_disallowed_type(db):
    assert is_auction_item_type_allowed(db, "mega_auctions", "motorcycle") is False


def test_is_auction_item_type_allowed_unknown_type_checks_other_bucket(db):
    cfg = SourceConfig(source="mega_auctions", source_type="auction", extra={"allowed_item_types": ["other"]})
    db.add(cfg)
    db.commit()

    assert is_auction_item_type_allowed(db, "mega", "spaceship") is True
