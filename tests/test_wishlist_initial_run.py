from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

from app.models.source_config import SourceConfig
from app.models.source_state import SourceState
from app.models.user import User
from app.services.source_execution_service import run_source_for_all_wishlists
from app.services.wishlists_service import add_wishlist


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


def test_add_wishlist_triggers_initial_run_and_feedback(db, monkeypatch):
    user = _make_user(db)
    calls: list[dict] = []

    def _fake_run(db_sess, source_name, **kwargs):
        calls.append({"source": source_name, **kwargs})
        return {"ok": True, "status": "success"}


    # precisamos do map com a wishlist recém-criada: resolve dinamicamente
    def _allowed(_db, wishlists):
        return {wishlists[0].id: {"olx"}}

    monkeypatch.setattr("app.services.wishlists_service.allowed_sources_for_wishlists", _allowed)
    monkeypatch.setattr("app.services.wishlists_service.run_source_for_all_wishlists", _fake_run)
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)

    ok, msg = add_wishlist(db, user.id, "civic si")

    assert ok is True
    assert "executada agora" in msg
    assert len(calls) == 1
    assert calls[0]["kind"] == "wishlist_created"
    assert calls[0]["force"] is True
    assert calls[0]["run_reason"] == "wishlist_created"


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


def test_add_wishlist_when_no_source_keeps_legacy_feedback(db, monkeypatch):
    user = _make_user(db)

    monkeypatch.setattr("app.services.wishlists_service.allowed_sources_for_wishlists", lambda *_: {})
    monkeypatch.setattr("app.services.wishlists_service.log", lambda *args, **kwargs: None)

    ok, msg = add_wishlist(db, user.id, "fusca")

    assert ok is True
    assert msg == "Wishlist criada."


def test_scheduler_not_due_after_recent_effective_run(db, monkeypatch):
    now = datetime.utcnow()

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
        "app.services.source_execution_service.scrape_ingest_match_many",
        lambda *args, **kwargs: {"ok": False, "reason": "blocked", "status_code": 200, "url": "https://www.webmotors.com.br/carros/estoque", "error": "WM_DIAG::{}"},
    )

    res = run_source_for_all_wishlists(db, "webmotors", kind="admin", force=True, ignore_backoff=True, run_reason="admin")

    assert res["status"] == "blocked"
    assert isinstance(res.get("duration_ms"), int)
    assert res["duration_ms"] >= 0
