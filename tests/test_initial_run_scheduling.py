from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.settings import settings
from app.models.scrape_job import ScrapeJob
from app.models.source_config import SourceConfig
from app.models.source_state import SourceState
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services import scrape_jobs_service
from app.services.initial_run_policy import INITIAL_RUN_PRIORITY
from app.services.wishlists_service import trigger_initial_run_for_wishlist


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *a, **k: None)
    monkeypatch.setattr(settings, "initial_run_cooldown_minutes", 30)
    monkeypatch.setattr(settings, "initial_run_debounce_min_seconds", 90)
    monkeypatch.setattr(settings, "initial_run_debounce_max_seconds", 120)
    monkeypatch.setattr(settings, "initial_run_backfill_max_notifications", 0)  # isola do backfill
    from app.services import source_configs_service

    source_configs_service._CACHE_BY_SOURCE.clear()


def _wishlist(db, sources=("olx",), monkeypatch=None):
    user = User(id=uuid.uuid4(), telegram_chat_id=int(uuid.uuid4().int % 10**9), username="u", is_active=True, plan="free")
    db.add(user)
    db.commit()
    w = Wishlist(id=uuid.uuid4(), user_id=user.id, query="civic si", is_active=True)
    db.add(w)
    db.commit()
    monkeypatch.setattr(
        "app.services.wishlists_service.allowed_sources_for_wishlists",
        lambda _db, wishlists: {wishlists[0].id: set(sources)},
    )
    return w


def _cfg(db, source="olx", extra=None):
    db.add(SourceConfig(source=source, is_enabled=True, sched_minutes=180, cooldown_minutes=0, rate_limit_seconds=0, extra=extra or {}))
    db.commit()


def _state(db, source="olx", *, ran_minutes_ago=None, next_allowed_in=None):
    now = datetime.now(timezone.utc)
    db.add(
        SourceState(
            source=source,
            last_effective_run_at=(now - timedelta(minutes=ran_minutes_ago)) if ran_minutes_ago is not None else None,
            next_allowed_at=(now + timedelta(minutes=next_allowed_in)) if next_allowed_in is not None else None,
            consecutive_blocks=0,
            consecutive_failures=0,
        )
    )
    db.commit()


def _capture_enqueue(monkeypatch, result=True):
    calls = []
    monkeypatch.setattr("app.services.wishlists_service.enqueue_job", lambda _db, **kw: calls.append(kw) or result)
    return calls


def test_first_run_is_debounced_with_initial_priority(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)
    _cfg(db)
    calls = _capture_enqueue(monkeypatch)

    before = datetime.now(timezone.utc)
    out = trigger_initial_run_for_wishlist(db, w)

    assert out["triggered"] == 1 and out["deferred"] == 0
    kw = calls[0]
    delay = (kw["run_at"] - before).total_seconds()
    assert 89 <= delay <= 121
    assert kw["priority"] == INITIAL_RUN_PRIORITY
    assert out["sources"][0]["status"] == "queued"
    assert 90 <= out["sources"][0]["run_in_seconds"] <= 120


def test_recent_run_defers_to_normal_cycle_without_enqueue(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)
    _cfg(db)
    _state(db, ran_minutes_ago=10)
    calls = _capture_enqueue(monkeypatch)

    out = trigger_initial_run_for_wishlist(db, w)

    assert calls == []
    assert out["triggered"] == 0 and out["deferred"] == 1 and out["skipped"] == 0
    assert out["sources"][0]["status"] == "deferred_cooldown"
    assert 0 < out["sources"][0]["retry_in_seconds"] <= 20 * 60


def test_old_run_does_not_defer(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)
    _cfg(db)
    _state(db, ran_minutes_ago=45)
    calls = _capture_enqueue(monkeypatch)

    out = trigger_initial_run_for_wishlist(db, w)

    assert len(calls) == 1 and out["deferred"] == 0


def test_source_in_backoff_is_deferred_not_enqueued(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)
    _cfg(db)
    _state(db, ran_minutes_ago=300, next_allowed_in=40)
    calls = _capture_enqueue(monkeypatch)

    out = trigger_initial_run_for_wishlist(db, w)

    assert calls == []
    assert out["sources"][0]["status"] == "deferred_backoff"
    assert out["deferred"] == 1


def test_per_source_cooldown_override(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)
    _cfg(db, extra={"initial_run": {"cooldown_minutes": 5}})
    _state(db, ran_minutes_ago=10)
    calls = _capture_enqueue(monkeypatch)

    trigger_initial_run_for_wishlist(db, w)

    assert len(calls) == 1


def test_active_job_is_coalesced_and_pulled_forward(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)
    _cfg(db)
    pulled = []
    monkeypatch.setattr("app.services.wishlists_service.enqueue_job", lambda _db, **kw: False)
    monkeypatch.setattr(
        "app.services.wishlists_service.pull_forward_active_job",
        lambda _db, **kw: pulled.append(kw) or True,
    )

    out = trigger_initial_run_for_wishlist(db, w)

    assert len(pulled) == 1 and pulled[0]["priority"] == INITIAL_RUN_PRIORITY
    assert out["sources"][0]["status"] == "coalesced"
    assert out["triggered"] == 1 and out["skipped"] == 0


def test_active_job_not_pullable_is_reported_as_already_running(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)
    _cfg(db)
    monkeypatch.setattr("app.services.wishlists_service.enqueue_job", lambda _db, **kw: False)
    monkeypatch.setattr("app.services.wishlists_service.pull_forward_active_job", lambda _db, **kw: False)

    out = trigger_initial_run_for_wishlist(db, w)

    assert out["sources"][0]["status"] == "already_queued"
    assert out["skipped"] == 1


def test_missing_source_state_and_config_does_not_block(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)  # sem SourceConfig/SourceState
    calls = _capture_enqueue(monkeypatch)

    out = trigger_initial_run_for_wishlist(db, w)

    assert len(calls) == 1 and out["deferred"] == 0


# ---- pull_forward_active_job (banco real/sqlite) ----

def _utc(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _job(db, *, run_at, status="queued", priority=0, source="olx", queue="http"):
    j = ScrapeJob(id=uuid.uuid4(), source=source, queue=queue, run_at=run_at, priority=priority, status=status, attempt=0, max_attempts=3)
    db.add(j)
    db.commit()
    return j


def test_pull_forward_moves_later_job_earlier_and_raises_priority(db):
    now = datetime.now(timezone.utc)
    j = _job(db, run_at=now + timedelta(hours=2), priority=0)
    target = now + timedelta(seconds=100)

    ok = scrape_jobs_service.pull_forward_active_job(db, source="olx", queue="http", run_at=target, priority=1)
    db.refresh(j)

    assert ok is True
    assert abs((_utc(j.run_at) - target).total_seconds()) < 1
    assert j.priority == 1


def test_pull_forward_never_postpones_an_earlier_job(db):
    now = datetime.now(timezone.utc)
    early = now + timedelta(seconds=30)
    j = _job(db, run_at=early, priority=1)

    ok = scrape_jobs_service.pull_forward_active_job(db, source="olx", queue="http", run_at=now + timedelta(seconds=100), priority=1)
    db.refresh(j)

    assert ok is True
    assert abs((_utc(j.run_at) - early).total_seconds()) < 1


def test_pull_forward_ignores_running_job(db):
    j = _job(db, run_at=datetime.now(timezone.utc), status="running")

    ok = scrape_jobs_service.pull_forward_active_job(db, source="olx", queue="http", run_at=datetime.now(timezone.utc), priority=1)

    assert ok is False


# ---- integracao com backfill e copy ----

def test_trigger_reports_immediate_results_from_stock_backfill(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)
    _cfg(db)
    _capture_enqueue(monkeypatch)
    seen = {}

    def _fake_backfill(_db, wishlist, **kw):
        seen.update(kw)
        return {"considered": 40, "matched": 4, "queued": 3, "cap_skipped": 1}

    monkeypatch.setattr("app.services.wishlists_service.backfill_wishlist_from_stock", _fake_backfill)
    monkeypatch.setattr(settings, "initial_run_backfill_hours", 72)
    monkeypatch.setattr(settings, "initial_run_backfill_max_notifications", 5)

    out = trigger_initial_run_for_wishlist(db, w)

    assert out["immediate_results"] == 3
    assert seen == {"sources": ["olx"], "hours": 72, "max_notifications": 5}


def test_backfill_runs_even_when_every_source_is_deferred(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)
    _cfg(db)
    _state(db, ran_minutes_ago=5)
    calls = _capture_enqueue(monkeypatch)
    monkeypatch.setattr(
        "app.services.wishlists_service.backfill_wishlist_from_stock",
        lambda _db, wishlist, **kw: {"queued": 2},
    )

    out = trigger_initial_run_for_wishlist(db, w)

    assert calls == [] and out["deferred"] == 1 and out["immediate_results"] == 2


def test_backfill_failure_does_not_break_trigger(db, monkeypatch):
    w = _wishlist(db, monkeypatch=monkeypatch)
    _cfg(db)
    calls = _capture_enqueue(monkeypatch)
    monkeypatch.setattr(
        "app.services.wishlists_service.backfill_wishlist_from_stock",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    out = trigger_initial_run_for_wishlist(db, w)

    assert len(calls) == 1 and out["immediate_results"] == 0


def test_feedback_copy_for_deferred_and_immediate():
    from app.bot.handlers_core import _render_initial_run_feedback as render

    assert "enviando agora" in render({"triggered": 1, "immediate_results": 2})
    deferred = render({"triggered": 0, "failed": 0, "skipped": 0, "deferred": 1})
    assert "monitoramento" in deferred.lower()
    assert "Nenhuma fonte disponível" not in deferred
    assert "varredura" not in deferred.lower()  # sem detalhe operacional ao usuario
    # comportamento anterior preservado
    assert "Nenhuma fonte disponível" in render({"triggered": 0, "failed": 0, "skipped": 1})
    assert "Primeira varredura em andamento" in render({"triggered": 1})


def test_add_wishlist_message_reflects_immediate_results_and_deferral(db, monkeypatch):
    from app.services.wishlists_service import add_wishlist

    user = User(id=uuid.uuid4(), telegram_chat_id=777, username="u", is_active=True, plan="free")
    db.add(user)
    db.commit()
    monkeypatch.setattr("app.services.wishlists_service.enqueue_fipe_lookup_for_wishlist", lambda *a, **k: None)

    monkeypatch.setattr(
        "app.services.wishlists_service.trigger_initial_run_for_wishlist",
        lambda *a, **k: {"triggered": 1, "failed": 0, "deferred": 0, "immediate_results": 2},
    )
    ok, msg = add_wishlist(db, user.id, "civic si")
    assert ok and "enviando agora" in msg and "segundo plano" not in msg

    monkeypatch.setattr(
        "app.services.wishlists_service.trigger_initial_run_for_wishlist",
        lambda *a, **k: {"triggered": 0, "failed": 0, "deferred": 1, "immediate_results": 0},
    )
    ok, msg = add_wishlist(db, user.id, "fusca")
    assert ok and "monitoramento" in msg.lower() and "segundo plano" not in msg
