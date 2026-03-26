from app.models.wishlist_tracked_listing import WishlistTrackedListing


def test_tracking_model_has_slot_range_check_constraint():
    constraints = {c.name for c in WishlistTrackedListing.__table__.constraints}
    assert "ck_wishlist_tracked_listing_slot_range" in constraints
