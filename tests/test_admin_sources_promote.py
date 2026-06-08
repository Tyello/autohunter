import asyncio
import json
from datetime import datetime, timedelta, timezone
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
        self._runs = runs or []

    def commit(self):
        return None

    def query(self, model):
        if getattr(model, "__name__", "") == "SourceRun":
            return _Query(self._runs)
        return _EmptyQuery()


class _EmptyQuery:
    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return []


class _Query(_EmptyQuery):
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


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


def _run(status="success", *, runtime_impl="v2_canary", dt=None, found=182, inserted=5, matched=8, queued=0, duration=83057):
    return SimpleNamespace(
        status=status,
        created_at=dt or datetime.now(timezone.utc),
        payload={"runtime_impl": runtime_impl},
        items_found=found,
        items_ingested=inserted,
        items_matched=matched,
        notifications_queued=queued,
        duration_ms=duration,
    )


def _healthy_runs():
    now = datetime.now(timezone.utc)
    return [
        _run(dt=now, found=182),
        _run(dt=now - timedelta(minutes=5), found=181),
        _run(dt=now - timedelta(minutes=10), found=180),
    ]


def _patch_common(monkeypatch, cfg, runs):
    def _set(_db, _source, _field, _value):
        payload = json.loads(_value)
        merged = dict(cfg.extra)
        merged.update(payload)
        cfg.extra = merged
        return cfg

    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx(_DB(runs=runs)))
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(mod, "get_source_config", lambda _db, _source: cfg)
    monkeypatch.setattr(mod, "set_source_field", _set)
    monkeypatch.setattr(mod.settings, "enable_playwright", True)


def test_admin_sources_promote_blocks_other_sources(monkeypatch):
    up = _Update()
    asyncio.run(mod.admin_sources_promote(up, "olx", "v2"))
    assert "Promoção bloqueada" in up.message.texts[-1]
    assert "Apenas mercadolivre" in up.message.texts[-1]


def test_admin_sources_promote_mercadolivre_healthy_soak_updates_extra(monkeypatch):
    cfg = _cfg(
        extra={
            "impl": "v1",
            "mercadolivre_v2_canary_enabled": True,
            "operational_role": "primary",
            "browser_timeout_ms": 45000,
        }
    )
    _patch_common(monkeypatch, cfg, _healthy_runs())

    up = _Update()
    asyncio.run(mod.admin_sources_promote(up, "mercadolivre", "v2"))

    out = up.message.texts[-1]
    assert cfg.extra["impl"] == "v2"
    assert cfg.extra["mercadolivre_v2_canary_enabled"] is False
    assert cfg.extra["operational_role"] == "primary"
    assert cfg.extra["browser_timeout_ms"] == 45000
    assert "promovido para V2 configurado" in out
    assert "configured_impl=v2" in out
    assert "soak: success=3 blocked=0 error=0 found_recent=182" in out
    assert "/admin sources rollback mercadolivre v1" in out


def test_admin_sources_promote_blocks_without_positive_found(monkeypatch):
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True})
    runs = [_run(found=0), _run(found=0), _run(found=0)]
    _patch_common(monkeypatch, cfg, runs)

    up = _Update()
    asyncio.run(mod.admin_sources_promote(up, "mercadolivre", "v2"))

    assert cfg.extra["impl"] == "v1"
    assert "canary sem sucesso recente com found > 0" in up.message.texts[-1]


def test_admin_sources_promote_blocks_with_recent_blocked_or_error(monkeypatch):
    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True})
    _patch_common(monkeypatch, cfg, [_run(status="blocked"), *_healthy_runs()])

    up = _Update()
    asyncio.run(mod.admin_sources_promote(up, "mercadolivre", "v2"))

    assert cfg.extra["impl"] == "v1"
    assert "blocked recente" in up.message.texts[-1]

    cfg = _cfg(extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True})
    _patch_common(monkeypatch, cfg, [_run(status="error"), *_healthy_runs()])
    up = _Update()
    asyncio.run(mod.admin_sources_promote(up, "mercadolivre", "v2"))

    assert cfg.extra["impl"] == "v1"
    assert "error recente" in up.message.texts[-1]


def test_admin_sources_rollback_sets_v1_preserving_extra(monkeypatch):
    cfg = _cfg(
        extra={
            "impl": "v2",
            "mercadolivre_v2_canary_enabled": True,
            "operational_role": "primary",
            "http_timeout_s": 25,
            "browser_wait_until": "domcontentloaded",
        }
    )
    _patch_common(monkeypatch, cfg, [])

    up = _Update()
    asyncio.run(mod.admin_sources_rollback(up, "mercadolivre", "v1"))

    assert cfg.extra["impl"] == "v1"
    assert cfg.extra["mercadolivre_v2_canary_enabled"] is False
    assert cfg.extra["operational_role"] == "primary"
    assert cfg.extra["http_timeout_s"] == 25
    assert cfg.extra["browser_wait_until"] == "domcontentloaded"
    assert "rollback para V1 configurado" in up.message.texts[-1]
