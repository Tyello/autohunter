from app.services.auction_source_config_service import (
    ensure_auction_source_configs,
    reconcile_auction_source_config_metadata,
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


def test_default_user_eligible_only_vip(db):
    ensure_auction_source_configs(db)
    assert list_user_eligible_auction_sources(db) == {"vip_auctions"}


def test_reconcile_existing_auction_rows_updates_metadata_only(db):
    vip = SourceConfig(
        source="vip_auctions",
        source_type="classified",
        is_enabled=False,
        user_eligible=False,
        status="active",
        extra={"allowed_item_types": ["car", "motorcycle"], "disabled_reason": "manual"},
    )
    win = SourceConfig(source="win_auctions", source_type="auction", is_enabled=False, user_eligible=True, status="experimental")
    copart = SourceConfig(source="copart_auctions", source_type="auction", is_enabled=False, user_eligible=False, status="needs_js_or_endpoint_study")
    sodre = SourceConfig(source="sodre_auctions", source_type="auction", is_enabled=True, user_eligible=False, status="needs_study")
    db.add_all([vip, win, copart, sodre])
    db.flush()

    changed = reconcile_auction_source_config_metadata(db)
    db.flush()

    assert changed >= 4
    assert vip.source_type == "auction"
    assert vip.status == "production_ready"
    assert vip.is_enabled is False
    assert vip.user_eligible is False
    assert vip.extra == {"allowed_item_types": ["car", "motorcycle"], "disabled_reason": "manual"}
    assert win.status == "functional_non_car"
    assert win.is_enabled is False
    assert win.user_eligible is True
    assert copart.status == "needs_study"
    assert sodre.status == "blocked/needs_study"


def test_ensure_reconciles_legacy_statuses_without_changing_operational_flags(db):
    vip = SourceConfig(source="vip_auctions", source_type="auction", is_enabled=False, user_eligible=False, status="active", extra={"allowed_item_types": ["car"]})
    db.add(vip)
    db.flush()

    ensure_auction_source_configs(db)
    db.refresh(vip)

    assert vip.status == "production_ready"
    assert vip.is_enabled is False
    assert vip.user_eligible is False
    assert vip.extra == {"allowed_item_types": ["car"]}
