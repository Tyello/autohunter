import asyncio
import types
from datetime import datetime, timedelta, timezone

from app.bot import handlers_admin
from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.models.system_log import SystemLog
from app.models.scrape_job import ScrapeJob


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


def test_admin_sources_24h_effective_runs_exposes_expected_window(db, monkeypatch):
    _add_source(db, source="sched60", age_minutes=600)
    now = datetime.now(timezone.utc)
    # only 2 effective runs in 24h even with sched=60m
    db.add(SourceRun(source="sched60", kind="scheduler", status="success", created_at=now - timedelta(hours=10)))
    db.add(SourceRun(source="sched60", kind="scheduler", status="success", created_at=now - timedelta(hours=5)))
    db.commit()

    monkeypatch.setattr(handlers_admin, "list_sources", lambda: [_Plugin("sched60")])

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))

    out = "\n".join(update.message.sent)
    assert "24h efetivas:" in out
    assert "total=3/24" in out
    assert "runs=" not in out


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


def test_admin_sources_global_stale_denominator_uses_only_critical_sources(db, monkeypatch):
    _add_source(db, source="critical_a", age_minutes=500)
    _add_source(db, source="critical_b", age_minutes=460)
    for i in range(5):
        _add_source(db, source=f"deprior_{i}", age_minutes=10)
    db.commit()

    plugins = [_Plugin("critical_a", role="primary"), _Plugin("critical_b", role="primary")]
    plugins.extend(_Plugin(f"deprior_{i}", role="deprioritized") for i in range(5))
    monkeypatch.setattr(handlers_admin, "list_sources", lambda: plugins)

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))
    out = "\n".join(update.message.sent)
    assert "Sources críticas stale: 2/2 (100%)" in out


def test_admin_sources_global_stale_with_recent_heartbeat_and_no_runs_shows_actionable_diag(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(SourceConfig(source="s1", is_enabled=True, sched_minutes=60, cooldown_minutes=0, rate_limit_seconds=0))
    db.add(SourceConfig(source="s2", is_enabled=True, sched_minutes=60, cooldown_minutes=0, rate_limit_seconds=0))
    db.add(SourceConfig(source="s3", is_enabled=True, sched_minutes=60, cooldown_minutes=0, rate_limit_seconds=0))
    db.add(SourceState(source="s1", last_run_at=None, last_status=None))
    db.add(SourceState(source="s2", last_run_at=None, last_status=None))
    db.add(SourceState(source="s3", last_run_at=None, last_status=None))
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(seconds=15)))
    db.add(ScrapeJob(source="s1", queue="http", run_at=now - timedelta(minutes=5), status="queued", attempt=0, max_attempts=3, priority=0))
    db.commit()

    monkeypatch.setattr(handlers_admin, "list_sources", lambda: [_Plugin("s1"), _Plugin("s2"), _Plugin("s3")])
    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))
    out = "\n".join(update.message.sent)
    assert "heartbeat recente, mas 0 source runs na janela" in out
    assert "provável falha no enqueue, workers ou persistência" in out
    assert "Fila scrape_jobs: queued=1 running=0" in out


def test_admin_sources_separates_effective_runs_from_operational_skips(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(SourceConfig(source="olx", is_enabled=True, sched_minutes=60, cooldown_minutes=0, rate_limit_seconds=0))
    db.add(SourceState(source="olx", last_run_at=now - timedelta(minutes=1), last_status="skipped:no_matching_wishlists"))
    db.add(SourceRun(source="olx", kind="scheduler", status="success", created_at=now - timedelta(hours=23), items_found=10, items_matched=1, duration_ms=1000))
    for i in range(89):
        db.add(
            SourceRun(
                source="olx",
                kind="scheduler",
                status="skipped",
                created_at=now - timedelta(minutes=i),
                payload={"reason": "no_matching_wishlists"},
            )
        )
    db.commit()

    monkeypatch.setattr(handlers_admin, "list_sources", lambda: [_Plugin("olx")])

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))
    out = "\n".join(update.message.sent)

    assert "runs=90/24" not in out
    assert "(375%)" not in out
    assert "24h efetivas: ok=1 err=0 blk=0 total=1/24 (4%)" in out
    assert "24h skips: 89" in out
    assert "eventos totais: 90" in out
    assert "last skipped at=" in out
    assert "reason=no_matching_wishlists" in out
    assert "last success at=" in out


def test_admin_sources_only_recent_skips_are_observable_not_stale(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(SourceConfig(source="mercadolivre", is_enabled=True, sched_minutes=60, cooldown_minutes=0, rate_limit_seconds=0))
    db.add(SourceState(source="mercadolivre", last_run_at=now - timedelta(minutes=2), last_status="skipped:no_active_wishlists"))
    db.add(
        SourceRun(
            source="mercadolivre",
            kind="scheduler",
            status="skipped",
            created_at=now - timedelta(minutes=2),
            payload={"reason": "no_active_wishlists"},
        )
    )
    db.commit()

    monkeypatch.setattr(handlers_admin, "list_sources", lambda: [_Plugin("mercadolivre")])

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))
    out = "\n".join(update.message.sent)

    assert "STALE" not in out
    assert "SKIP" in out
    assert "last skipped at=" in out
    assert "reason=no_active_wishlists" in out
    assert "24h efetivas: ok=0 err=0 blk=0 total=0/24 (0%)" in out
    assert "24h skips: 1" in out


def test_admin_sources_recent_error_is_effective_and_not_masked_by_later_skips(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(SourceConfig(source="chavesnamao", is_enabled=True, sched_minutes=60, cooldown_minutes=0, rate_limit_seconds=0))
    db.add(SourceState(source="chavesnamao", last_run_at=now - timedelta(minutes=1), last_status="skipped:backoff"))
    db.add(SourceRun(source="chavesnamao", kind="scheduler", status="error", created_at=now - timedelta(minutes=10), error="Timeout while fetching"))
    db.add(SourceRun(source="chavesnamao", kind="scheduler", status="skipped", created_at=now - timedelta(minutes=1), payload={"reason": "backoff"}))
    db.commit()

    monkeypatch.setattr(handlers_admin, "list_sources", lambda: [_Plugin("chavesnamao")])

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))
    out = "\n".join(update.message.sent)

    assert "24h efetivas: ok=0 err=1 blk=0 total=1/24 (4%)" in out
    assert "24h skips: 1" in out
    assert "last skipped at=" in out
    assert "last effective error at=" in out
    assert "NET" in out or "ERR" in out or "BUG" in out or "DATA" in out


def test_admin_sources_experimental_stale_does_not_contaminate_critical_health(db, monkeypatch):
    _add_source(db, source="primary_src", age_minutes=20)
    _add_source(db, source="experimental_src", age_minutes=500)
    db.commit()

    monkeypatch.setattr(
        handlers_admin,
        "list_sources",
        lambda: [_Plugin("primary_src", role="primary"), _Plugin("experimental_src", role="experimental")],
    )

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))
    out = "\n".join(update.message.sent)

    assert "experimental_src" in out
    assert "note: role=experimental (stale não crítico em /admin health)" in out
    assert "Sources críticas stale:" not in out


def test_admin_sources_renders_zero_result_suspect_for_mercadolivre_canary(db, monkeypatch):
    now = datetime.now(timezone.utc)
    payload = {
        "runtime_impl": "v2_canary",
        "suspicious_zero_results": True,
        "zero_result_reason": "found_zero_with_recent_positive_baseline",
        "zero_result_baseline_found": 3,
        "run_summary": {
            "status": "OK",
            "found": 0,
            "inserted": 0,
            "matched": 0,
            "queued": 0,
            "suspicious_zero_results": True,
            "zero_result_reason": "found_zero_with_recent_positive_baseline",
            "zero_result_baseline_found": 3,
        },
    }
    db.add(
        SourceConfig(
            source="mercadolivre",
            is_enabled=True,
            sched_minutes=60,
            cooldown_minutes=0,
            rate_limit_seconds=0,
            browser_fallback_enabled=True,
            extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True},
        )
    )
    db.add(SourceState(source="mercadolivre", last_run_at=now - timedelta(minutes=5), last_status="success", last_payload=payload))
    db.add(
        SourceRun(
            source="mercadolivre",
            kind="scheduler",
            status="success",
            created_at=now - timedelta(minutes=5),
            duration_ms=8715,
            items_found=0,
            items_matched=0,
            payload=payload,
        )
    )
    db.commit()

    monkeypatch.setattr(handlers_admin, "list_sources", lambda: [_Plugin("mercadolivre")])

    update = _Update()
    asyncio.run(handlers_admin._admin_sources(update, verbose=False))
    out = "\n".join(update.message.sent)

    assert "zero_result_suspect" in out
    assert "found=0 com baseline recente positivo" in out
    assert "/admin sources canary mercadolivre report" in out
