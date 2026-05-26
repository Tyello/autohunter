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
        class _Q:
            def filter(self, *_args, **_kwargs):
                return self
            def one_or_none(self):
                return None
        class _DB:
            def query(self, _model):
                return _Q()
        return _DB()

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
    assert "configured_impl=v1" in out
    assert "mercadolivre_v2_canary_enabled=False" in out


def test_admin_sources_show_displays_impl_and_canary_from_extra(monkeypatch):
    cfg = SimpleNamespace(
        source="mercadolivre",
        is_enabled=True,
        sched_minutes=60,
        cooldown_minutes=0,
        rate_limit_seconds=0,
        proxy_server=None,
        browser_fallback_enabled=True,
        force_browser=False,
        extra={"impl": "v2", "mercadolivre_v2_canary_enabled": True},
    )
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)

    up = _Update()
    asyncio.run(mod.admin_sources_show(up, "mercadolivre"))

    out = up.message.texts[-1]
    assert "configured_impl=v2" in out
    assert "mercadolivre_v2_canary_enabled=True" in out


def test_admin_sources_show_displays_last_runtime_impl(monkeypatch):
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
    st = SimpleNamespace(last_status="success", last_payload={"runtime_impl": "v2_canary", "run_summary": {"runtime_impl": "v2_canary"}})

    class _Q:
        def filter(self, *_args, **_kwargs):
            return self
        def one_or_none(self):
            return st
    class _DB:
        def query(self, _model):
            return _Q()

    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(_Ctx, "__enter__", lambda self: _DB())

    up = _Update()
    asyncio.run(mod.admin_sources_show(up, "mercadolivre"))
    out = up.message.texts[-1]
    assert "configured_impl=v1" in out
    assert "last_runtime_impl=v2_canary" in out


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


def test_admin_sources_show_adds_operational_reading_for_webmotors_blocked_perimeterx(monkeypatch):
    cfg = SimpleNamespace(
        source="webmotors",
        is_enabled=True,
        sched_minutes=90,
        cooldown_minutes=0,
        rate_limit_seconds=0,
        proxy_server=None,
        browser_fallback_enabled=True,
        force_browser=True,
        extra={"operational_role": "deprioritized"},
    )
    st = SimpleNamespace(last_status="blocked", last_payload={"blocked_provider": "perimeterx"})

    class _Q:
        def filter(self, *_args, **_kwargs):
            return self

        def one_or_none(self):
            return st

    class _DB:
        def query(self, _model):
            return _Q()

    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(_Ctx, "__enter__", lambda self: _DB())

    up = _Update()
    asyncio.run(mod.admin_sources_show(up, "webmotors"))

    out = up.message.texts[-1]
    assert "leitura=source despriorizada por bloqueio PerimeterX/fingerprint" in out


def test_admin_sources_show_adds_operational_reading_for_webmotors_blocked_without_provider(monkeypatch):
    cfg = SimpleNamespace(
        source="webmotors",
        is_enabled=True,
        sched_minutes=90,
        cooldown_minutes=0,
        rate_limit_seconds=0,
        proxy_server=None,
        browser_fallback_enabled=True,
        force_browser=True,
        extra={"operational_role": "deprioritized"},
    )
    st = SimpleNamespace(last_status="blocked", last_payload={})

    class _Q:
        def filter(self, *_args, **_kwargs):
            return self

        def one_or_none(self):
            return st

    class _DB:
        def query(self, _model):
            return _Q()

    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(_Ctx, "__enter__", lambda self: _DB())

    up = _Update()
    asyncio.run(mod.admin_sources_show(up, "webmotors"))

    out = up.message.texts[-1]
    assert "leitura=source despriorizada; último status blocked; execução manual disponível, sem falha crítica global." in out
