import asyncio
import json
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
    def commit(self):
        return None


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
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)

    up = _Update()
    asyncio.run(mod.admin_sources_canary(up, "mercadolivre", "status"))

    out = up.message.texts[-1]
    assert "canary_effective=True" in out


def test_admin_sources_canary_status_reason_when_not_effective(monkeypatch):
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
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
