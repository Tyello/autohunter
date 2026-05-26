import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.bot import admin_handlers_sources as mod


class _Msg:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text):
        self.texts.append(text)


class _Update:
    def __init__(self):
        self.message = _Msg()


class _DB:
    def __init__(self, runs=None):
        self.runs = runs or []

    def commit(self):
        return None

    def query(self, model):
        assert model.__name__ == "SourceRun"
        return _Query(self.runs)


class _Query:
    def __init__(self, runs):
        self._runs = runs

    def filter(self, *conditions):
        out = self._runs
        for cond in conditions:
            left = getattr(cond, "left", None)
            right = getattr(cond, "right", None)
            col = getattr(left, "name", None)
            val = getattr(right, "value", right)
            if col == "source":
                out = [r for r in out if getattr(r, "source", None) == val]
            elif col == "created_at":
                out = [r for r in out if getattr(r, "created_at", None) >= val]
        self._runs = out
        return self

    def order_by(self, *_args, **_kwargs):
        self._runs = sorted(self._runs, key=lambda r: r.created_at, reverse=True)
        return self

    def all(self):
        return list(self._runs)


class _Ctx:
    def __init__(self, db=None):
        self._db = db or _DB()

    def __enter__(self):
        return self._db

    def __exit__(self, exc_type, exc, tb):
        return False


def _cfg(extra=None, browser_fallback_enabled=True):
    return SimpleNamespace(
        source="mercadolivre",
        is_enabled=True,
        sched_minutes=60,
        cooldown_minutes=0,
        rate_limit_seconds=0,
        proxy_server=None,
        browser_fallback_enabled=browser_fallback_enabled,
        force_browser=False,
        extra=extra or {},
    )


def _run(*, status="success", runtime_impl="v2_canary", created_at=None, payload=None, found=0, inserted=0, matched=0, queued=0, dur=0):
    now = created_at or datetime.utcnow()
    payload_val = payload if payload is not None else {"runtime_impl": runtime_impl}
    return SimpleNamespace(
        source="mercadolivre",
        status=status,
        created_at=now,
        payload=payload_val,
        items_found=found,
        items_ingested=inserted,
        items_matched=matched,
        notifications_queued=queued,
        duration_ms=dur,
    )


def test_admin_sources_canary_on_merges_extra_and_preserves_keys(monkeypatch):
    cfg = _cfg(extra={"x": 1, "impl": "v2"}, browser_fallback_enabled=True)
    seen = {}

    def _set(_db, _source, _field, _value):
        seen["source"] = _source
        seen["field"] = _field
        payload = json.loads(_value)
        seen["payload"] = payload
        merged = dict(cfg.extra)
        merged.update(payload)
        cfg.extra = merged
        return cfg

    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod, "set_source_field", _set)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)

    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "on"))

    out = up.message.texts[-1]
    assert seen["source"] == "mercadolivre"
    assert seen["field"] == "extra"
    assert seen["payload"]["impl"] == "v1"
    assert seen["payload"]["mercadolivre_v2_canary_enabled"] is True
    assert cfg.extra["x"] == 1
    assert "canary_effective=True" in out


def test_admin_sources_canary_off_sets_flag_false_preserving_other_keys(monkeypatch):
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True, "x": 1})

    def _set(_db, _source, _field, _value):
        payload = json.loads(_value)
        merged = dict(cfg.extra)
        merged.update(payload)
        cfg.extra = merged
        return cfg

    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod, "set_source_field", _set)

    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "off"))

    out = up.message.texts[-1]
    assert cfg.extra["x"] == 1
    assert cfg.extra["mercadolivre_v2_canary_enabled"] is False
    assert "V2 canary desativado" in out


def test_admin_sources_canary_status_effective_true(monkeypatch):
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True}, browser_fallback_enabled=True)
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx(_DB()))
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)

    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "status"))

    out = up.message.texts[-1]
    assert "canary_effective=True" in out


def test_admin_sources_canary_status_reason_when_not_effective(monkeypatch):
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx(_DB()))
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)

    # flag false
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": False}, browser_fallback_enabled=True)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)
    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "status"))
    assert "reason=canary_flag_disabled" in up.message.texts[-1]

    # playwright false
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True}, browser_fallback_enabled=True)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", False)
    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "status"))
    assert "reason=playwright_disabled" in up.message.texts[-1]

    # fallback false
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True}, browser_fallback_enabled=False)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)
    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "status"))
    assert "reason=browser_fallback_disabled" in up.message.texts[-1]


def test_admin_sources_canary_blocks_other_sources(monkeypatch):
    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "olx", "on"))
    assert "apenas para mercadolivre" in up.message.texts[-1]


def test_canary_status_without_v2_runs_recommends_manual_validation(monkeypatch):
    old_run = _run(status="success", runtime_impl="v1")
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True})
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx(_DB([old_run])))
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)
    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "status"))
    out = up.message.texts[-1]
    assert "v2_canary_success=0" in out
    assert "recommendation=run_manual_validation" in out


def test_canary_status_with_one_success_recommends_continue_soak(monkeypatch):
    run = _run(status="success", found=186, inserted=5, matched=8, queued=0, dur=87132)
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True})
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx(_DB([run])))
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)
    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "status"))
    out = up.message.texts[-1]
    assert "v2_canary_success=1" in out
    assert "last_success_found=186" in out
    assert "last_success_inserted=5" in out
    assert "last_success_matched=8" in out
    assert "last_success_queued=0" in out
    assert "last_success_duration_ms=87132" in out
    assert "recommendation=continue_soak" in out


def test_canary_status_with_three_successes_recommends_candidate(monkeypatch):
    now = datetime.utcnow()
    runs = [
        _run(status="success", created_at=now),
        _run(status="success", created_at=now - timedelta(minutes=5)),
        _run(status="success", created_at=now - timedelta(minutes=10)),
    ]
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True})
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx(_DB(runs)))
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)
    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "status"))
    assert "recommendation=continue_soak_candidate" in up.message.texts[-1]


def test_canary_status_with_blocked_recommends_review(monkeypatch):
    runs = [_run(status="blocked"), _run(status="success")]
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True})
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx(_DB(runs)))
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)
    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "report"))
    out = up.message.texts[-1]
    assert "v2_canary_blocked=1" in out
    assert "recommendation=keep_canary_or_rollback_review" in out


def test_canary_status_with_flag_off_recommends_not_effective(monkeypatch):
    runs = [_run(status="success")]
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": False})
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx(_DB(runs)))
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)
    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "status"))
    out = up.message.texts[-1]
    assert "canary_effective=False" in out
    assert "recommendation=canary_not_effective" in out


def test_canary_status_ignores_legacy_payload_without_runtime_impl(monkeypatch):
    runs = [_run(status="success", payload={}), _run(status="success", runtime_impl="v2_canary")]
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True})
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx(_DB(runs)))
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)
    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "status"))
    assert "v2_canary_success=1" in up.message.texts[-1]
