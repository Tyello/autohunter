from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.initial_backfill_service import backfill_wishlist_from_stock


def _wishlist(db, query="civic si"):
    user = User(id=uuid.uuid4(), telegram_chat_id=int(uuid.uuid4().int % 10**9), username="u", is_active=True, plan="free")
    db.add(user)
    db.commit()
    w = Wishlist(id=uuid.uuid4(), user_id=user.id, query=query, is_active=True)
    db.add(w)
    db.commit()
    return w


def _listing(db, title, *, source="olx", seen_hours_ago=1, sold=False, status="ativo", price="80000"):
    row = CarListing(
        id=uuid.uuid4(),
        source=source,
        external_id=str(uuid.uuid4()),
        title=title,
        url=f"https://example.com/{uuid.uuid4()}",
        price=price,
        is_sold=sold,
        status=status,
        last_seen_at=datetime.now(timezone.utc) - timedelta(hours=seen_hours_ago),
    )
    db.add(row)
    db.commit()
    return row


def _notified(db, w):
    return db.query(Notification).filter(Notification.wishlist_id == w.id).count()


def test_backfill_queues_matching_recent_stock_only(db):
    w = _wishlist(db)
    ok = _listing(db, "Honda Civic Si 2008")
    _listing(db, "Honda Fit 2010")                                  # nao casa
    _listing(db, "Honda Civic Si 2007", sold=True)                   # vendido
    _listing(db, "Honda Civic Si 2006", status="inativo")            # inativo
    _listing(db, "Honda Civic Si 2009", seen_hours_ago=200)          # fora da janela
    _listing(db, "Honda Civic Si 2010", source="kavak")              # source nao permitida

    out = backfill_wishlist_from_stock(db, w, sources={"olx"}, hours=72, max_notifications=5)
    db.commit()

    assert out["queued"] == 1 and out["matched"] == 1
    assert _notified(db, w) == 1
    assert db.query(Notification).filter(Notification.wishlist_id == w.id).one().car_listing_id == ok.id


def test_backfill_respects_notification_cap(db):
    w = _wishlist(db)
    for i in range(8):
        _listing(db, f"Honda Civic Si {2000 + i}")

    out = backfill_wishlist_from_stock(db, w, sources={"olx"}, hours=72, max_notifications=3)
    db.commit()

    assert out["queued"] == 3 and out["cap_skipped"] == 5
    assert _notified(db, w) == 3


def test_backfill_is_idempotent(db):
    w = _wishlist(db)
    _listing(db, "Honda Civic Si 2008")

    backfill_wishlist_from_stock(db, w, sources={"olx"}, hours=72, max_notifications=5)
    db.commit()
    again = backfill_wishlist_from_stock(db, w, sources={"olx"}, hours=72, max_notifications=5)
    db.commit()

    assert again["queued"] == 0
    assert _notified(db, w) == 1


def test_backfill_disabled_or_without_sources_does_nothing(db):
    w = _wishlist(db)
    _listing(db, "Honda Civic Si 2008")

    assert backfill_wishlist_from_stock(db, w, sources={"olx"}, hours=72, max_notifications=0)["queued"] == 0
    assert backfill_wishlist_from_stock(db, w, sources=set(), hours=72, max_notifications=5)["queued"] == 0
    assert _notified(db, w) == 0


def test_backfill_failure_never_raises(db, monkeypatch):
    w = _wishlist(db)
    monkeypatch.setattr(
        "app.services.initial_backfill_service.match_listings_for_wishlists",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _listing(db, "Honda Civic Si 2008")

    out = backfill_wishlist_from_stock(db, w, sources={"olx"}, hours=72, max_notifications=5)

    assert out["queued"] == 0 and out["error"] == "RuntimeError"
