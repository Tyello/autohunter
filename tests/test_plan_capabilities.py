from app.services.plan_capabilities import get_plan_capabilities


def test_free_capabilities_defaults():
    caps = get_plan_capabilities("free")
    assert caps.max_active_wishlists == 2
    assert caps.max_tracked_per_wishlist == 1
    assert caps.tracking_auto_alerts is False
    assert caps.daily_notification_limit == 10


def test_premium_and_legacy_codes_map_to_premium():
    for code in ("premium", "pro", "ultra"):
        caps = get_plan_capabilities(code)
        assert caps.max_active_wishlists == 10
        assert caps.max_tracked_per_wishlist == 3
        assert caps.tracking_auto_alerts is True
        assert caps.daily_notification_limit == 50
