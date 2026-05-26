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


class _DB:
    def commit(self):
        return None


class _Ctx:
    def __enter__(self):
        return _DB()

    def __exit__(self, exc_type, exc, tb):
        return False


def test_admin_sources_set_extra_updates_without_error_and_reports_canary(monkeypatch):
    cfg = SimpleNamespace(
        source="mercadolivre",
        is_enabled=True,
        sched_minutes=60,
        cooldown_minutes=0,
        rate_limit_seconds=0,
        proxy_server=None,
        browser_fallback_enabled=True,
        force_browser=False,
        extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True},
    )

    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "set_source_field", lambda _db, _source, _field, _value: cfg)

    up = _Update()
    asyncio.run(mod.admin_sources_set_simple(up, "mercadolivre", "extra", '{"mercadolivre_v2_canary_enabled":true}'))

    out = up.message.texts[-1]
    assert "Erro:" not in out
    assert "extra=updated" in out
    assert "mercadolivre_v2_canary_enabled=True" in out
