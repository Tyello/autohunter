from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.source_execution_service import run_source_for_all_wishlists
from app.services.wishlists_service import add_wishlist, create_wishlist_with_filters, list_filters
from app.sources.types import ScrapeContext
from app.sources.types import SourcePlugin


def _make_user(db):
    user = User(
        id=uuid.uuid4(),
        telegram_chat_id=123456789,
        username="tester",
        is_active=True,
        plan="free",
    )
    db.add(user)
    db.commit()
    return user


def test_queue_execution_without_active_wishlists_updates_source_observability(db, monkeypatch):
    db.add(
        SourceConfig(
            source="olx",
            is_enabled=True,
            user_eligible=True,
            sched_minutes=60,
            cooldown_minutes=0,
            rate_limit_seconds=0,
        )
    )
    db.commit()

    monkeypatch.setattr("app.services.source_execution_service.log", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.source_execution_service.emit_event", lambda *args, **kwargs: None)

    res = run_source_for_all_wishlists(db, "olx", kind="queue", force=False, run_reason="queue")

    assert res["status"] == "skipped"
    assert res["reason"] == "no_active_wishlists"

    state = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert state.last_run_at is not None
    assert state.last_effective_run_at is None
    assert state.last_status == "skipped:no_active_wishlists"
    assert state.last_payload["active_wishlists"] == 0

    run = db.query(SourceRun).filter(SourceRun.source == "olx").one()
    assert run.kind == "queue"
    assert run.status == "skipped"
    assert run.payload["reason"] == "no_active_wishlists"
    assert run.payload["active_wishlists"] == 0


def test_add_wishlist_triggers_initial_run_and_feedback(db, monkeypatch):
    user = _make_user(db)
    calls: list[dict] = []

    def _fake_enqueue(db_sess, **kwargs):
        calls.append(kwargs)
        return True


    # precisamos do map com a wishlist recém-criada: resolve dinamicamente
    def _allowed(_db, wishlists):
        return {wishlists[0].id: {"olx"}}

    monkeypatch.setattr("app.services.wishlists_service.allowed_sources_for_wishlists", _allowed)
    monkeypatch.setattr("app.services.wishlists_service.enqueue_job", _fake_enqueue)
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)

    ok, msg = add_wishlist(db, user.id, "civic si")

    assert ok is True
    assert "primeira busca em segundo plano" in msg
    assert len(calls) == 1
    assert calls[0]["source"] == "olx"
    assert calls[0]["queue"] == "http"


def test_add_wishlist_browser_source_uses_browser_queue(db, monkeypatch):
    user = _make_user(db)
    calls: list[dict] = []
    browser_plugin = SourcePlugin(
        name="olx",
        build_url=lambda _q: "https://example.com",
        scrape=lambda _u, _ctx: [],
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="browser",
        default_extra={"operational_role": "primary"},
    )

    monkeypatch.setattr("app.services.wishlists_service.allowed_sources_for_wishlists", lambda _db, wishlists: {wishlists[0].id: {"olx"}})
    monkeypatch.setattr("app.services.wishlists_service.get_source", lambda _src: browser_plugin)
    monkeypatch.setattr("app.services.wishlists_service.enqueue_job", lambda _db, **kwargs: calls.append(kwargs) or True)
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)

    ok, _msg = add_wishlist(db, user.id, "jetta gli")

    assert ok is True
    assert len(calls) == 1
    assert calls[0]["queue"] == "browser"


def test_add_wishlist_queue_override_uses_default_extra_queue(db, monkeypatch):
    user = _make_user(db)
    calls: list[dict] = []
    plugin = SourcePlugin(
        name="olx",
        build_url=lambda _q: "https://example.com",
        scrape=lambda _u, _ctx: [],
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="http",
        default_extra={"operational_role": "primary", "queue": "browser"},
    )

    monkeypatch.setattr("app.services.wishlists_service.allowed_sources_for_wishlists", lambda _db, wishlists: {wishlists[0].id: {"olx"}})
    monkeypatch.setattr("app.services.wishlists_service.get_source", lambda _src: plugin)
    monkeypatch.setattr("app.services.wishlists_service.enqueue_job", lambda _db, **kwargs: calls.append(kwargs) or True)
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)

    ok, _msg = add_wishlist(db, user.id, "compass")

    assert ok is True
    assert len(calls) == 1
    assert calls[0]["queue"] == "browser"


def test_add_wishlist_non_monitoring_source_is_not_enqueued(db, monkeypatch):
    user = _make_user(db)
    plugin = SourcePlugin(
        name="olx",
        build_url=lambda _q: "https://example.com",
        scrape=lambda _u, _ctx: [],
        supports_manual_search=True,
        supports_wishlist_monitoring=False,
        fetch_mode="http",
        default_extra={"operational_role": "auxiliary"},
    )

    monkeypatch.setattr("app.services.wishlists_service.allowed_sources_for_wishlists", lambda _db, wishlists: {wishlists[0].id: {"olx"}})
    monkeypatch.setattr("app.services.wishlists_service.get_source", lambda _src: plugin)
    monkeypatch.setattr("app.services.wishlists_service.enqueue_job", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("should not enqueue")))
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)

    ok, msg = add_wishlist(db, user.id, "fusca")

    assert ok is True
    assert "Wishlist criada" in msg


def test_add_wishlist_creation_failure_does_not_trigger_initial_run(db, monkeypatch):
    user = _make_user(db)
    called = {"v": False}

    def _fake_trigger(*args, **kwargs):
        called["v"] = True
        return {"triggered": 1}

    monkeypatch.setattr("app.services.wishlists_service.trigger_initial_run_for_wishlist", _fake_trigger)

    ok, msg = add_wishlist(db, user.id, "")

    assert ok is False
    assert "Query inválida" in msg
    assert called["v"] is False


def test_add_wishlist_when_no_source_still_succeeds(db, monkeypatch):
    user = _make_user(db)

    monkeypatch.setattr("app.services.wishlists_service.allowed_sources_for_wishlists", lambda *_: {})
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)

    ok, msg = add_wishlist(db, user.id, "fusca")

    assert ok is True
    assert "Wishlist criada" in msg


def test_add_wishlist_can_skip_initial_run_when_disabled(db, monkeypatch):
    user = _make_user(db)
    called = {"n": 0}
    monkeypatch.setattr(
        "app.services.wishlists_service.trigger_initial_run_for_wishlist",
        lambda *_args, **_kwargs: called.update(n=called["n"] + 1),
    )
    ok, _msg = add_wishlist(db, user.id, "fusca", enqueue_initial_run=False)
    assert ok is True
    assert called["n"] == 0


def test_create_wishlist_with_filters_enqueues_after_persisting_filters(db, monkeypatch):
    user = _make_user(db)
    calls = []
    monkeypatch.setattr(
        "app.services.wishlists_service.trigger_initial_run_for_wishlist",
        lambda _db, _w, **_kwargs: calls.append("run") or {"triggered": 1, "failed": 0},
    )
    monkeypatch.setattr("app.services.wishlists_service.allowed_sources_for_wishlists", lambda *_: {})
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)
    ok, _msg, wishlist_id = create_wishlist_with_filters(
        db,
        user.id,
        "civic si",
        [{"field": "state", "operator": "eq", "value": "São Paulo"}, {"field": "state", "operator": "eq", "value": "SP"}],
    )
    assert ok is True
    assert wishlist_id is not None
    rows = list_filters(db, wishlist_id)
    assert len(rows) == 1
    assert rows[0].field == "state"
    assert rows[0].value == "SP"
    assert calls == ["run"]


def test_create_wishlist_with_invalid_filter_does_not_enqueue(db, monkeypatch):
    user = _make_user(db)
    calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.wishlists_service.trigger_initial_run_for_wishlist",
        lambda *_args, **_kwargs: calls.update(n=calls["n"] + 1),
    )
    ok, msg, wishlist_id = create_wishlist_with_filters(
        db,
        user.id,
        "civic si",
        [{"field": "state", "operator": "eq", "value": "estado inexistente"}],
    )
    assert ok is False
    assert "UF com 2 letras" in msg
    assert wishlist_id is None
    assert calls["n"] == 0
    assert db.query(Wishlist).filter(Wishlist.user_id == user.id).count() == 0


def test_scheduler_not_due_after_recent_effective_run(db, monkeypatch):
    now = datetime.now(timezone.utc)

    db.add(
        SourceConfig(
            source="olx",
            is_enabled=True,
            sched_minutes=30,
            cooldown_minutes=0,
            rate_limit_seconds=0,
            browser_fallback_enabled=False,
            force_browser=False,
        )
    )
    db.add(
        SourceState(
            source="olx",
            last_effective_run_at=now,
            last_run_at=now,
            consecutive_blocks=0,
            consecutive_failures=0,
        )
    )
    db.commit()
    monkeypatch.setattr("app.services.source_execution_service._utcnow", lambda: now)

    res = run_source_for_all_wishlists(db, "olx", kind="scheduler", force=False, run_reason="scheduler")

    assert res["ok"] is True
    assert res["status"] == "skipped"
    assert res["reason"] == "not_due"


def test_manual_run_reason_is_propagated_on_skips(db):
    db.add(
        SourceConfig(
            source="olx",
            is_enabled=False,
            sched_minutes=30,
            cooldown_minutes=0,
            rate_limit_seconds=0,
            browser_fallback_enabled=False,
            force_browser=False,
        )
    )
    db.commit()

    res = run_source_for_all_wishlists(db, "olx", kind="wishlist_created", force=False, run_reason="wishlist_created")

    assert res["ok"] is True
    assert res["status"] == "skipped"
    assert res["run_reason"] == "wishlist_created"


def test_blocked_run_includes_duration_ms(db, monkeypatch):
    db.add(
        SourceConfig(
            source="webmotors",
            is_enabled=True,
            sched_minutes=30,
            cooldown_minutes=1,
            rate_limit_seconds=0,
            browser_fallback_enabled=True,
            force_browser=False,
            extra={},
        )
    )
    db.commit()

    plugin = SimpleNamespace(
        name="webmotors",
        scrape=lambda *args, **kwargs: [],
        build_url=lambda _q: "https://www.webmotors.com.br/carros/estoque",
        fetch_mode="http",
        supports_wishlist_monitoring=False,
    )
    monkeypatch.setattr("app.services.source_execution_service.get_source", lambda _src: plugin)
    monkeypatch.setattr("app.services.source_execution_service.ensure_source_configs", lambda _db: None)
    monkeypatch.setattr("app.services.source_execution_service.get_scraper", lambda _src: None)
    monkeypatch.setattr("app.services.source_execution_service.log", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.source_execution_service.emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.source_execution_service.scrape_ingest_match",
        lambda *args, **kwargs: {"ok": False, "reason": "blocked", "status_code": 200, "url": "https://www.webmotors.com.br/carros/estoque", "error": "WM_DIAG::{}"},
    )

    res = run_source_for_all_wishlists(db, "webmotors", kind="admin", force=True, ignore_backoff=True, run_reason="admin")

    assert res["status"] == "blocked"
    assert isinstance(res.get("duration_ms"), int)
    assert res["duration_ms"] >= 0


def test_scrape_context_allows_runtime_metadata_slots():
    ctx = ScrapeContext(source="olx")

    object.__setattr__(ctx, "_last_adapter_meta", {"impl": "v1"})
    object.__setattr__(ctx, "_matching_stats", {"matched_wishlists": 2})
    object.__setattr__(ctx, "_hybrid_browser_used", True)

    assert ctx._last_adapter_meta == {"impl": "v1"}
    assert ctx._matching_stats == {"matched_wishlists": 2}
    assert ctx._hybrid_browser_used is True

def test_add_wishlist_enqueue_failure_does_not_block_creation(db, monkeypatch):
    user = _make_user(db)

    def _allowed(_db, wishlists):
        return {wishlists[0].id: {"olx"}}

    monkeypatch.setattr("app.services.wishlists_service.allowed_sources_for_wishlists", _allowed)
    monkeypatch.setattr("app.services.wishlists_service.enqueue_job", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)

    ok, msg = add_wishlist(db, user.id, "civic")

    assert ok is True
    assert "Não consegui agendar" in msg


def test_add_wishlist_enqueue_failure_in_one_source_does_not_block_others(db, monkeypatch):
    user = _make_user(db)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "app.services.wishlists_service.allowed_sources_for_wishlists",
        lambda _db, wishlists: {wishlists[0].id: {"olx", "mercadolivre"}},
    )
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)

    def _fake_enqueue(_db, **kwargs):
        calls.append((kwargs["source"], kwargs["queue"]))
        if kwargs["source"] == "olx":
            raise RuntimeError("boom")
        return True

    monkeypatch.setattr("app.services.wishlists_service.enqueue_job", _fake_enqueue)

    ok, msg = add_wishlist(db, user.id, "civic touring")

    assert ok is True
    assert "primeira busca em segundo plano" in msg
    assert {src for src, _queue in calls} == {"olx", "mercadolivre"}


def test_create_wishlist_with_filters_returns_success_when_initial_enqueue_fails(db, monkeypatch):
    user = _make_user(db)

    monkeypatch.setattr(
        "app.services.wishlists_service.allowed_sources_for_wishlists",
        lambda _db, wishlists: {wishlists[0].id: {"olx"}},
    )
    monkeypatch.setattr(
        "app.services.wishlists_service.enqueue_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)

    ok, msg, wishlist_id = create_wishlist_with_filters(
        db,
        user.id,
        "civic touring",
        [{"field": "year", "operator": "gte", "value": "2018"}],
    )

    assert ok is True
    assert wishlist_id is not None
    assert "sucesso" in msg.lower()
