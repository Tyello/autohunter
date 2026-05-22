import asyncio
import types
from datetime import datetime, timedelta, timezone

from app.bot import handlers_admin
from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.models.source_state import SourceState


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, txt):
        self.sent.append(txt)


class _Update:
    def __init__(self):
        self.message = _Msg()


class _Plugin:
    def __init__(self, name: str, *, role: str = "primary"):
        self.name = name
        self.scrape = lambda _url, _ctx: []
        self.default_enabled = True
        self.default_sched_minutes = 60
        self.default_cooldown_minutes = 0
        self.default_rate_limit_seconds = 0
        self.default_proxy_server = None
        self.default_browser_fallback_enabled = False
        self.default_force_browser = False
        self.default_extra = {"operational_role": role}


def _add_source(db, *, source: str, enabled: bool = True, sched_m: int = 60, status: str = "success", age_minutes: int = 10):
    now = datetime.now(timezone.utc)
    db.add(SourceConfig(source=source, is_enabled=enabled, sched_minutes=sched_m, cooldown_minutes=0, rate_limit_seconds=0))
    if status:
        t = now - timedelta(minutes=age_minutes)
        db.add(SourceRun(source=source, kind="scheduler", status=status, created_at=t))
        db.add(SourceState(source=source, last_run_at=t, last_status=status))


def test_admin_sources_marks_stale_and_global_hint(db, monkeypatch):
    _add_source(db, source="s1", age_minutes=500)
    _add_source(db, source="s2", age_minutes=460)
    _add_source(db, source="s3", age_minutes=470)
    db.commit()

    monkeypatch.setattr(handlers_admin, "list_sources", lambda: [_Plugin("s1"), _Plugin("s2"), _Plugin("s3")])

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))

    out = "\n".join(update.message.sent)
    assert "STALE" in out
    assert "indício global" in out


def test_admin_sources_recent_run_keeps_ok(db, monkeypatch):
    _add_source(db, source="oksrc", age_minutes=20)
    db.commit()
    monkeypatch.setattr(handlers_admin, "list_sources", lambda: [_Plugin("oksrc")])

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))

    out = "\n".join(update.message.sent)
    assert "✅ OK" in out
    assert "STALE" not in out


def test_admin_sources_24h_runs_exposes_expected_window(db, monkeypatch):
    _add_source(db, source="sched60", age_minutes=600)
    now = datetime.now(timezone.utc)
    # only 2 runs in 24h even with sched=60m
    db.add(SourceRun(source="sched60", kind="scheduler", status="success", created_at=now - timedelta(hours=10)))
    db.add(SourceRun(source="sched60", kind="scheduler", status="success", created_at=now - timedelta(hours=5)))
    db.commit()

    monkeypatch.setattr(handlers_admin, "list_sources", lambda: [_Plugin("sched60")])

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))

    out = "\n".join(update.message.sent)
    assert "runs=" in out
    assert "/24" in out


def test_admin_sources_preserves_disabled_and_error_states(db, monkeypatch):
    _add_source(db, source="disabled_src", enabled=False, status="success", age_minutes=20)
    _add_source(db, source="error_src", enabled=True, status="error", age_minutes=20)
    db.commit()

    monkeypatch.setattr(handlers_admin, "list_sources", lambda: [_Plugin("disabled_src"), _Plugin("error_src")])

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))

    out = "\n".join(update.message.sent)
    assert "DISABLED" in out
    assert "ERR" in out or "BUG" in out or "NET" in out or "DATA" in out


def test_admin_sources_deprioritized_blocked_is_non_critical(db, monkeypatch):
    _add_source(db, source="olx", status="blocked", age_minutes=10)
    _add_source(db, source="webmotors", status="blocked", age_minutes=10)
    db.commit()

    monkeypatch.setattr(
        handlers_admin,
        "list_sources",
        lambda: [_Plugin("olx", role="primary"), _Plugin("webmotors", role="deprioritized")],
    )

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))
    out = "\n".join(update.message.sent)
    assert "webmotors" in out
    assert "role=deprioritized não crítico global" in out
    assert "Blocked 24h: crítico=1 não_crítico=1" in out
