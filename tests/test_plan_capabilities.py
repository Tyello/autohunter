from app.services.plan_capabilities import get_plan_capabilities, normalize_plan_code


def test_free_capabilities_defaults():
    caps = get_plan_capabilities("free")
    assert caps.max_active_wishlists == 2
    assert caps.max_tracked_total == 1
    assert caps.max_tracked_slots_per_wishlist == 3
    assert caps.tracking_auto_alerts is False
    assert caps.daily_notifications_per_wishlist == 5


def test_premium_code_maps_to_premium_capabilities():
    caps = get_plan_capabilities("premium")
    assert caps.max_active_wishlists == 15
    assert caps.max_tracked_total == 5
    assert caps.max_tracked_slots_per_wishlist == 3
    assert caps.tracking_auto_alerts is True
    assert caps.daily_notifications_per_wishlist == 200
    assert caps.launch_price_brl == 5.99
    assert caps.future_price_brl == 9.99


def test_legacy_codes_fallback_to_free():
    for code in ("pro", "ultra", "paid"):
        assert normalize_plan_code(code) == "free"
        caps = get_plan_capabilities(code)
        assert caps.plan_code == "free"
        assert caps.premium is False
