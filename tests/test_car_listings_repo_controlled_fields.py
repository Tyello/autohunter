from app.repositories.car_listings_repo import _normalize_controlled_fields


def test_controlled_fields_are_sanitized_to_db_domain():
    row = _normalize_controlled_fields(
        {
            "fuel_type": "Unknown",
            "transmission": "Unknown",
            "seller_type": "unknown",
            "listing_type": "invalid",
        }
    )

    assert row["fuel_type"] is None
    assert row["transmission"] is None
    assert row["seller_type"] == "unknown"
    assert row["listing_type"] == "marketplace"


def test_controlled_fields_accept_canonical_values():
    row = _normalize_controlled_fields(
        {
            "fuel_type": "diesel",
            "transmission": "manual",
            "seller_type": "private",
            "listing_type": "classified",
        }
    )

    assert row["fuel_type"] == "diesel"
    assert row["transmission"] == "manual"
    assert row["seller_type"] == "private"
    assert row["listing_type"] == "classified"
