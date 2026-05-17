from app.scheduler import auction_notification_job as mod


def _runtime(enabled=False, dry_run=True, kill_switch=False, max_wishlists=20, max_per_wishlist=1, max_per_user_per_day=3):
    return {
        "enabled": enabled if not kill_switch else False,
        "dry_run": dry_run,
        "max_wishlists_per_run": max_wishlists,
        "max_per_wishlist": max_per_wishlist,
        "max_per_user_per_day": max_per_user_per_day,
        "kill_switch": kill_switch,
    }


def test_scheduler_skips_when_disabled(db, monkeypatch):
    monkeypatch.setattr(mod, "get_auction_notification_runtime_settings", lambda _db: _runtime(enabled=False, dry_run=True))
    calls = {"ran": 0}

    async def _fake(*_a, **_k):
        calls["ran"] += 1
        return {}

    monkeypatch.setattr(mod, "run_auction_notification_job", _fake)
    out = mod.run_scheduled_auction_notification_job(db)
    assert out["skipped"] is True
    assert out["reason"] == "disabled"
    assert calls["ran"] == 0


def test_scheduler_calls_dry_run(db, monkeypatch):
    monkeypatch.setattr(mod, "get_auction_notification_runtime_settings", lambda _db: _runtime(enabled=True, dry_run=True))
    seen = {}

    async def _fake(db, **kwargs):
        seen.update(kwargs)
        return {"sent": 0, "previews": 2, "skipped_no_match": 0, "skipped_duplicate": 0, "skipped_daily_limit": 0, "errors": 0}

    monkeypatch.setattr(mod, "run_auction_notification_job", _fake)
    out = mod.run_scheduled_auction_notification_job(db)
    assert out["skipped"] is False
    assert seen["dry_run"] is True
    assert seen["bot"] is None


def test_scheduler_requires_bot_for_real_send(db, monkeypatch):
    monkeypatch.setattr(mod, "get_auction_notification_runtime_settings", lambda _db: _runtime(enabled=True, dry_run=False))
    out = mod.run_scheduled_auction_notification_job(db, bot=None)
    assert out["skipped"] is True
    assert out["reason"] == "bot_unavailable_for_real_send"


def test_scheduler_calls_real_send_with_bot(db, monkeypatch):
    monkeypatch.setattr(mod, "get_auction_notification_runtime_settings", lambda _db: _runtime(enabled=True, dry_run=False))
    seen = {}

    async def _fake(db, **kwargs):
        seen.update(kwargs)
        return {"sent": 1, "previews": 0, "skipped_no_match": 0, "skipped_duplicate": 0, "skipped_daily_limit": 0, "errors": 0}

    monkeypatch.setattr(mod, "run_auction_notification_job", _fake)
    bot = object()
    out = mod.run_scheduled_auction_notification_job(db, bot=bot)
    assert out["skipped"] is False
    assert seen["dry_run"] is False
    assert seen["bot"] is bot


def test_scheduler_lock_already_running(db, monkeypatch):
    monkeypatch.setattr(mod, "get_auction_notification_runtime_settings", lambda _db: _runtime(enabled=True, dry_run=True))
    assert mod._AUCTION_NOTIFICATION_SCHEDULER_LOCK.acquire(blocking=False)
    try:
        out = mod.run_scheduled_auction_notification_job(db)
        assert out["skipped"] is True
        assert out["reason"] == "already_running"
    finally:
        mod._AUCTION_NOTIFICATION_SCHEDULER_LOCK.release()


def test_scheduler_propagates_limits(db, monkeypatch):
    monkeypatch.setattr(mod, "get_auction_notification_runtime_settings", lambda _db: _runtime(enabled=True, dry_run=True, max_wishlists=8, max_per_wishlist=2, max_per_user_per_day=4))
    seen = {}

    async def _fake(db, **kwargs):
        seen.update(kwargs)
        return {"sent": 0, "previews": 0, "skipped_no_match": 0, "skipped_duplicate": 0, "skipped_daily_limit": 0, "errors": 0}

    monkeypatch.setattr(mod, "run_auction_notification_job", _fake)
    mod.run_scheduled_auction_notification_job(db)
    assert seen["max_wishlists"] == 8
    assert seen["max_per_wishlist"] == 2
    assert seen["max_per_user_per_day"] == 4


def test_scheduler_kill_switch_forces_disabled(db, monkeypatch):
    monkeypatch.setattr(mod, "get_auction_notification_runtime_settings", lambda _db: _runtime(enabled=True, dry_run=False, kill_switch=True))
    out = mod.run_scheduled_auction_notification_job(db, bot=object())
    assert out["skipped"] is True
    assert out["reason"] == "disabled"
