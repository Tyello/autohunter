from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models.car_listing import CarListing
from app.models.source_config import SourceConfig
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_listing_activity import WishlistListingActivity
from app.services.listing_activity_service import build_seen_identity, reconcile_listing_activity_for_source_run
from app.services.source_execution_service import run_source_for_all_wishlists


def _mk_user(db, *, chat_id: int = 111) -> User:
    u = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=True, plan="free")
    db.add(u)
    db.commit()
    return u


def _mk_wishlist(db, user: User, query: str = "civic") -> Wishlist:
    w = Wishlist(id=uuid.uuid4(), user_id=user.id, query=query, is_active=True)
    db.add(w)
    db.commit()
    return w


def _mk_listing(db, *, source: str = "olx", external_id: str = "1", title: str = "civic", url: str | None = None) -> CarListing:
    l = CarListing(
        id=uuid.uuid4(),
        source=source,
        external_id=external_id,
        title=title,
        url=url or f"https://example.test/{source}/{external_id}",
        currency="BRL",
        extras={},
    )
    db.add(l)
    db.commit()
    return l


def test_listing_seen_stays_active_and_resets_missing(db):
    user = _mk_user(db)
    wl = _mk_wishlist(db, user)
    listing = _mk_listing(db, external_id="same")
    ident = build_seen_identity(listing)

    reconcile_listing_activity_for_source_run(
        db,
        source_name="olx",
        wishlist_seen={wl.id: [ident]},
        target_wishlist_ids=[wl.id],
        missing_threshold=3,
    )
    db.commit()

    row = db.query(WishlistListingActivity).filter_by(wishlist_id=wl.id).one()
    row.missing_runs_count = 2
    db.commit()

    reconcile_listing_activity_for_source_run(
        db,
        source_name="olx",
        wishlist_seen={wl.id: [ident]},
        target_wishlist_ids=[wl.id],
        missing_threshold=3,
    )
    db.commit()

    row = db.query(WishlistListingActivity).filter_by(wishlist_id=wl.id).one()
    assert row.status == "active"
    assert row.missing_runs_count == 0


def test_missing_one_valid_run_does_not_inactivate(db):
    user = _mk_user(db)
    wl = _mk_wishlist(db, user)
    listing = _mk_listing(db, external_id="a")
    ident = build_seen_identity(listing)

    reconcile_listing_activity_for_source_run(
        db,
        source_name="olx",
        wishlist_seen={wl.id: [ident]},
        target_wishlist_ids=[wl.id],
        missing_threshold=3,
    )
    reconcile_listing_activity_for_source_run(
        db,
        source_name="olx",
        wishlist_seen={wl.id: []},
        target_wishlist_ids=[wl.id],
        missing_threshold=3,
    )
    db.commit()

    row = db.query(WishlistListingActivity).filter_by(wishlist_id=wl.id).one()
    assert row.status == "active"
    assert row.missing_runs_count == 1


def test_inactivates_after_threshold_and_reactivates_when_reappears(db):
    user = _mk_user(db)
    wl = _mk_wishlist(db, user)
    listing = _mk_listing(db, external_id="x")
    ident = build_seen_identity(listing)

    reconcile_listing_activity_for_source_run(db, source_name="olx", wishlist_seen={wl.id: [ident]}, target_wishlist_ids=[wl.id], missing_threshold=3)
    reconcile_listing_activity_for_source_run(db, source_name="olx", wishlist_seen={wl.id: []}, target_wishlist_ids=[wl.id], missing_threshold=3)
    reconcile_listing_activity_for_source_run(db, source_name="olx", wishlist_seen={wl.id: []}, target_wishlist_ids=[wl.id], missing_threshold=3)
    reconcile_listing_activity_for_source_run(db, source_name="olx", wishlist_seen={wl.id: []}, target_wishlist_ids=[wl.id], missing_threshold=3)
    db.commit()

    row = db.query(WishlistListingActivity).filter_by(wishlist_id=wl.id).one()
    assert row.status == "inactive"
    assert row.missing_runs_count >= 3
    assert row.inactive_at is not None

    reconcile_listing_activity_for_source_run(db, source_name="olx", wishlist_seen={wl.id: [ident]}, target_wishlist_ids=[wl.id], missing_threshold=3)
    db.commit()

    row = db.query(WishlistListingActivity).filter_by(wishlist_id=wl.id).one()
    assert row.status == "active"
    assert row.missing_runs_count == 0
    assert row.reactivated_at is not None


def test_missing_is_isolated_per_wishlist_and_does_not_delete_data(db):
    user = _mk_user(db)
    wl1 = _mk_wishlist(db, user, "civic")
    wl2 = _mk_wishlist(db, user, "corolla")
    listing = _mk_listing(db, external_id="same-ad")
    ident = build_seen_identity(listing)

    reconcile_listing_activity_for_source_run(
        db,
        source_name="olx",
        wishlist_seen={wl1.id: [ident], wl2.id: [ident]},
        target_wishlist_ids=[wl1.id, wl2.id],
        missing_threshold=2,
    )
    reconcile_listing_activity_for_source_run(
        db,
        source_name="olx",
        wishlist_seen={wl1.id: [], wl2.id: [ident]},
        target_wishlist_ids=[wl1.id, wl2.id],
        missing_threshold=2,
    )
    db.commit()

    rows = db.query(WishlistListingActivity).all()
    assert len(rows) == 2
    r1 = db.query(WishlistListingActivity).filter_by(wishlist_id=wl1.id).one()
    r2 = db.query(WishlistListingActivity).filter_by(wishlist_id=wl2.id).one()
    assert r1.missing_runs_count == 1
    assert r1.status == "active"
    assert r2.missing_runs_count == 0
    assert r2.status == "active"


def test_run_failure_does_not_increment_missing(db, monkeypatch):
    db.add(
        SourceConfig(
            source="olx",
            is_enabled=True,
            sched_minutes=10,
            cooldown_minutes=0,
            rate_limit_seconds=0,
            browser_fallback_enabled=False,
            force_browser=False,
        )
    )
    db.commit()

    user = _mk_user(db)
    wl = _mk_wishlist(db, user)
    listing = _mk_listing(db, source="olx", external_id="runfail")
    ident = build_seen_identity(listing)

    reconcile_listing_activity_for_source_run(
        db,
        source_name="olx",
        wishlist_seen={wl.id: [ident]},
        target_wishlist_ids=[wl.id],
        missing_threshold=2,
    )
    db.commit()

    plugin = SimpleNamespace(
        name="olx",
        scrape=lambda *_args, **_kwargs: [],
        build_url=lambda q: f"https://example.test/olx?q={q or ''}",
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
        lambda *args, **kwargs: {"ok": False, "reason": "error", "error": "boom", "url": "https://example.test/olx"},
    )

    run_source_for_all_wishlists(db, "olx", kind="admin", force=True, ignore_backoff=True, run_reason="admin")

    row = db.query(WishlistListingActivity).filter_by(wishlist_id=wl.id).one()
    assert row.missing_runs_count == 0
    assert row.status == "active"


def test_multiple_sources_keep_independent_activity_states(db):
    user = _mk_user(db)
    wl = _mk_wishlist(db, user)
    olx_listing = _mk_listing(db, source="olx", external_id="z")
    ml_listing = _mk_listing(db, source="mercadolivre", external_id="z")

    reconcile_listing_activity_for_source_run(
        db,
        source_name="olx",
        wishlist_seen={wl.id: [build_seen_identity(olx_listing)]},
        target_wishlist_ids=[wl.id],
        missing_threshold=2,
    )
    reconcile_listing_activity_for_source_run(
        db,
        source_name="mercadolivre",
        wishlist_seen={wl.id: [build_seen_identity(ml_listing)]},
        target_wishlist_ids=[wl.id],
        missing_threshold=2,
    )
    reconcile_listing_activity_for_source_run(
        db,
        source_name="olx",
        wishlist_seen={wl.id: []},
        target_wishlist_ids=[wl.id],
        missing_threshold=2,
    )
    db.commit()

    olx_row = db.query(WishlistListingActivity).filter_by(wishlist_id=wl.id, source_name="olx").one()
    ml_row = db.query(WishlistListingActivity).filter_by(wishlist_id=wl.id, source_name="mercadolivre").one()

    assert olx_row.missing_runs_count == 1
    assert ml_row.missing_runs_count == 0
