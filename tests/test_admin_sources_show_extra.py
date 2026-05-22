import asyncio
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


class _Ctx:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


def test_admin_sources_show_includes_sanitized_extra(monkeypatch):
    cfg = SimpleNamespace(
        source="webmotors",
        is_enabled=True,
        sched_minutes=90,
        cooldown_minutes=0,
        rate_limit_seconds=0,
        proxy_server=None,
        browser_fallback_enabled=True,
        force_browser=True,
        extra={"browser_block_resources": False, "api_token": "abc", "operational_role": "deprioritized"},
    )
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)

    up = _Update()
    asyncio.run(mod.admin_sources_show(up, "webmotors"))

    out = up.message.texts[-1]
    assert "extra={" in out
    assert '"browser_block_resources":false' in out
    assert '"operational_role":"deprioritized"' in out
    assert '"api_token":"***"' in out


def test_admin_sources_show_extra_none(monkeypatch):
    cfg = SimpleNamespace(
        source="webmotors",
        is_enabled=True,
        sched_minutes=90,
        cooldown_minutes=0,
        rate_limit_seconds=0,
        proxy_server=None,
        browser_fallback_enabled=True,
        force_browser=True,
        extra=None,
    )
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)

    up = _Update()
    asyncio.run(mod.admin_sources_show(up, "webmotors"))

    assert "extra=-" in up.message.texts[-1]
