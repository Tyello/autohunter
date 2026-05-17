from app.services.app_kv_service import get_kv
from app.services.auction_notification_settings_service import get_auction_notification_runtime_settings, set_runtime_setting, reset_runtime_setting


def test_settings_fallback_to_env(db, monkeypatch):
    monkeypatch.setattr('app.services.auction_notification_settings_service.settings.auction_notifications_min_score', 77)
    out = get_auction_notification_runtime_settings(db)
    assert out['min_score'] == 77
    assert out['source']['min_score'] == 'env'


def test_settings_runtime_overrides_and_reset(db):
    set_runtime_setting(db, 'min_score', 88, updated_by='1')
    out = get_auction_notification_runtime_settings(db)
    assert out['min_score'] == 88
    assert out['source']['min_score'] == 'runtime'
    reset_runtime_setting(db, 'min_score', updated_by='1')
    out2 = get_auction_notification_runtime_settings(db)
    assert out2['source']['min_score'] == 'env'


def test_kill_switch_forces_disabled(db, monkeypatch):
    set_runtime_setting(db, 'enabled', True, updated_by='1')
    monkeypatch.setattr('app.services.auction_notification_settings_service.settings.auction_notifications_kill_switch', True)
    out = get_auction_notification_runtime_settings(db)
    assert out['enabled_raw'] is True
    assert out['enabled'] is False
    assert out['kill_switch'] is True
