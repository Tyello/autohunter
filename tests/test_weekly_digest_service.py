from datetime import datetime, timedelta, timezone
import uuid

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.weekly_digest_service import build_weekly_digest_for_user


def _mk_user(db, chat_id=9001):
    u = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username="u", is_active=True)
    db.add(u)
    db.commit()
    return u


def _mk_wl(db, user, q="civic"):
    wl = Wishlist(user_id=user.id, query=q, is_active=True)
    db.add(wl)
    db.commit()
    return wl


def _mk_listing(db, ext="x", title="Car", price=10000):
    l = CarListing(source="olx", external_id=ext, title=title, url=f"https://x/{ext}", price=price, location="SP")
    db.add(l)
    db.commit()
    return l


def _mk_notif(db, user, wl, listing, *, days_ago=0, reason="match", score=80):
    n = Notification(user_id=user.id, wishlist_id=wl.id, car_listing_id=listing.id, status="sent", reason=reason, score_v2=score, sent_at=datetime.now(timezone.utc)-timedelta(days=days_ago))
    db.add(n)
    db.commit()


def test_digest_empty(db):
    u = _mk_user(db)
    payload = build_weekly_digest_for_user(db, user_id=u.id)
    assert payload["totals"]["sent"] == 0
    assert payload["top_opportunities"] == []


def test_digest_counts_and_top(db):
    u = _mk_user(db)
    wl = _mk_wl(db, u)
    l1 = _mk_listing(db, "1", "A")
    l2 = _mk_listing(db, "2", "B")
    _mk_notif(db, u, wl, l1, score=70)
    _mk_notif(db, u, wl, l2, score=90)
    p = build_weekly_digest_for_user(db, user_id=u.id)
    assert p["totals"]["sent"] == 2
    assert p["by_wishlist"][0]["count"] == 2
    assert p["top_opportunities"][0]["title"] == "B"


def test_digest_window_and_price_drop_dedup(db):
    u = _mk_user(db)
    wl = _mk_wl(db, u)
    l = _mk_listing(db, "1", "Drop")
    _mk_notif(db, u, wl, l, days_ago=10, reason="tracked_price_drop", score=50)
    _mk_notif(db, u, wl, l, days_ago=1, reason="tracked_price_drop", score=60)
    _mk_notif(db, u, wl, l, days_ago=1, reason="tracked_price_drop", score=61)
    p = build_weekly_digest_for_user(db, user_id=u.id, days=7)
    assert p["totals"]["sent"] == 2
    assert len(p["top_opportunities"]) == 1
    assert len(p["price_drops"]) == 1
