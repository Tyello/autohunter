from app.services.auction_source_config_service import (
    ensure_auction_source_configs,
    is_auction_source_enabled,
    is_auction_source_user_eligible,
    list_enabled_auction_sources,
    list_user_eligible_auction_sources,
)
from app.models.source_config import SourceConfig


def test_bootstrap_defaults(db):
    ensure_auction_source_configs(db)
    assert is_auction_source_user_eligible(db, "vip_auctions") is True
    assert is_auction_source_user_eligible(db, "mega_auctions") is False
    assert is_auction_source_enabled(db, "copart_auctions") is False
    assert "vip_auctions" in list_user_eligible_auction_sources(db)
    assert "copart_auctions" not in list_enabled_auction_sources(db)


def test_existing_auction_row_retypes_without_overwriting_operational_decisions(db):
    row = SourceConfig(
        source="vip_auctions",
        source_type="classified",
        is_enabled=False,
        user_eligible=False,
    )
    db.add(row)
    db.flush()

    ensure_auction_source_configs(db)
    db.refresh(row)

    assert row.source_type == "auction"
    assert row.is_enabled is False
    assert row.user_eligible is False
