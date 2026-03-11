from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models.source_config import SourceConfig
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.source_execution_service import run_source_for_all_wishlists


def _mk_user(db, *, chat_id: int = 111) -> User:
    u = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=True, plan="free")
    db.add(u)
    db.commit()
    return u


def _mk_cfg(db, source: str = "olx"):
    db.add(
        SourceConfig(
            source=source,
            is_enabled=True,
            sched_minutes=10,
            cooldown_minutes=0,
            rate_limit_seconds=0,
            browser_fallback_enabled=False,
            force_browser=False,
        )
    )
    db.commit()


def _patch_runtime(monkeypatch, *, source_name: str = "olx"):
    plugin = SimpleNamespace(
        name=source_name,
        scrape=lambda *_args, **_kwargs: [],
        build_url=lambda q: f"https://example.test/{source_name}?q={q or ''}",
        fetch_mode="http",
        supports_wishlist_monitoring=True,
    )
    monkeypatch.setattr("app.services.source_execution_service.get_source", lambda _src: plugin)
    monkeypatch.setattr("app.services.source_execution_service.ensure_source_configs", lambda _db: None)
    monkeypatch.setattr("app.services.source_execution_service.get_scraper", lambda _src: None)
    monkeypatch.setattr("app.services.source_execution_service.log", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.source_execution_service.emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.source_execution_service.scrape_ingest_match_many",
        lambda *args, **kwargs: {
            "ok": True,
            "found": 0,
            "inserted": 0,
            "matched": 0,
            "queued": 0,
            "already_notified": 0,
            "reason_buckets": {},
            "thumb_present": 0,
        },
    )


def test_runall_with_eligible_wishlist_does_not_skip(db, monkeypatch):
    _mk_cfg(db, "olx")
    user = _mk_user(db)
    db.add(Wishlist(id=uuid.uuid4(), user_id=user.id, query="civic", is_active=True))
    db.commit()
    _patch_runtime(monkeypatch, source_name="olx")

    res = run_source_for_all_wishlists(db, "olx", kind="admin", force=True, ignore_backoff=True, run_reason="admin")

    assert res["status"] == "success"
    assert res.get("filtered_by_plan", 0) == 0


def test_runall_skips_when_only_inactive_wishlist_exists(db, monkeypatch):
    _mk_cfg(db, "olx")
    user = _mk_user(db)
    db.add(Wishlist(id=uuid.uuid4(), user_id=user.id, query="civic", is_active=False))
    db.commit()
    _patch_runtime(monkeypatch, source_name="olx")

    res = run_source_for_all_wishlists(db, "olx", kind="admin", force=True, ignore_backoff=True, run_reason="admin")

    assert res["status"] == "skipped"
    assert res["reason"] == "no_active_wishlists"
    assert res["total_wishlists"] == 1
    assert res["active_wishlists"] == 0
    assert res["eligible_wishlists"] == 0
    assert res["filtered_by_disabled"] == 1


def test_runall_reports_source_binding_filter(db, monkeypatch):
    _mk_cfg(db, "olx")
    user = _mk_user(db)
    wl = Wishlist(id=uuid.uuid4(), user_id=user.id, query="civic", is_active=True)
    db.add(wl)
    db.commit()
    db.add(WishlistFilter(wishlist_id=wl.id, field="source", operator="eq", value="mercadolivre"))
    db.commit()
    _patch_runtime(monkeypatch, source_name="olx")

    res = run_source_for_all_wishlists(db, "olx", kind="admin", force=True, ignore_backoff=True, run_reason="admin")

    assert res["status"] == "skipped"
    assert res["reason"] == "no_matching_wishlists"
    assert res["total_wishlists"] == 1
    assert res["active_wishlists"] == 1
    assert res["eligible_wishlists"] == 0
    assert res["filtered_by_source_binding"] == 1
