from app.services.plan_capabilities import get_plan_capabilities


def test_free_capabilities_defaults():
    caps = get_plan_capabilities("free")
    assert caps.max_active_wishlists == 2
    assert caps.max_tracked_total == 1
    assert caps.max_tracked_slots_per_wishlist == 3
    assert caps.tracking_auto_alerts is False
    assert caps.daily_notifications_per_wishlist == 5


def test_premium_and_legacy_codes_map_to_premium():
    for code in ("premium", "pro", "ultra", "paid"):
        caps = get_plan_capabilities(code)
        assert caps.max_active_wishlists == 15
        assert caps.max_tracked_total == 5
        assert caps.max_tracked_slots_per_wishlist == 3
        assert caps.tracking_auto_alerts is True
        assert caps.daily_notifications_per_wishlist == 200
        assert caps.launch_price_brl == 5.99
        assert caps.future_price_brl == 9.99
