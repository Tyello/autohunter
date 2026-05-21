from __future__ import annotations

from types import SimpleNamespace


def test_bootstrap_source_configs_once_calls_ensure(monkeypatch):
    from app.scheduler import run as run_mod

    called = {"ensure": 0, "log": 0, "commit": 0}

    class _DB:
        def commit(self):
            called["commit"] += 1

    class _Ctx:
        def __enter__(self):
            return _DB()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(run_mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(run_mod, "ensure_source_configs", lambda _db: ["olx"])
    monkeypatch.setattr(run_mod, "log", lambda *_a, **_k: called.__setitem__("log", called["log"] + 1))

    run_mod._bootstrap_source_configs_once()

    assert called["commit"] == 2
    assert called["log"] == 1


def test_job_tick_does_not_call_ensure_source_configs_when_cfg_exists(monkeypatch):
    from app.scheduler import run as run_mod

    ensure_called = {"count": 0}
    enqueued = {"count": 0}

    class _DB:
        def commit(self):
            return None

    class _Ctx:
        def __enter__(self):
            return _DB()

        def __exit__(self, exc_type, exc, tb):
            return False

    plugin = SimpleNamespace(name="olx", scrape=lambda *_a, **_k: [], fetch_mode="http")
    cfg = SimpleNamespace(is_enabled=True, force_browser=False, sched_minutes=1)
    allowed = SimpleNamespace(is_allowed=True)

    monkeypatch.setattr(run_mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(run_mod, "get_source", lambda _src: plugin)
    monkeypatch.setattr(run_mod, "_get_cfg", lambda _db, _src: cfg)
    monkeypatch.setattr(run_mod, "_get_state", lambda _db, _src: None)
    monkeypatch.setattr(run_mod, "is_source_allowed", lambda *_a, **_k: allowed)
    monkeypatch.setattr(run_mod, "enqueue_job", lambda *_a, **_k: enqueued.__setitem__("count", enqueued["count"] + 1) or True)
    monkeypatch.setattr(run_mod, "ensure_source_configs", lambda _db: ensure_called.__setitem__("count", ensure_called["count"] + 1))

    run_mod.job_run_source_for_all_wishlists("olx")

    assert ensure_called["count"] == 0
    assert enqueued["count"] == 1


def test_job_tick_with_missing_cfg_returns_without_crashing(monkeypatch):
    from app.scheduler import run as run_mod

    called = {"enqueue": 0}

    class _DB:
        def commit(self):
            return None

    class _Ctx:
        def __enter__(self):
            return _DB()

        def __exit__(self, exc_type, exc, tb):
            return False

    plugin = SimpleNamespace(name="olx", scrape=lambda *_a, **_k: [], fetch_mode="http")

    monkeypatch.setattr(run_mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(run_mod, "get_source", lambda _src: plugin)
    monkeypatch.setattr(run_mod, "_get_cfg", lambda _db, _src: None)
    monkeypatch.setattr(run_mod, "enqueue_job", lambda *_a, **_k: called.__setitem__("enqueue", called["enqueue"] + 1))

    run_mod.job_run_source_for_all_wishlists("olx")

    assert called["enqueue"] == 0
