from datetime import datetime, timedelta, timezone
import uuid

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.weekly_digest_service import build_weekly_digest_candidates, build_weekly_digest_for_user
from app.services.weekly_digest_preferences_service import set_weekly_digest_enabled


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


def _mk_notif(db, user, wl, listing, *, days_ago=0, reason="match", score=80, sent_at=None):
    n = Notification(user_id=user.id, wishlist_id=wl.id, car_listing_id=listing.id, status="sent", reason=reason, score_v2=score, sent_at=sent_at or (datetime.now(timezone.utc)-timedelta(days=days_ago)))
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


def test_price_drop_dedup_keeps_most_recent_item(db):
    u = _mk_user(db)
    wl = _mk_wl(db, u)
    l = _mk_listing(db, "99", "Mesmo carro")
    older = datetime.now(timezone.utc) - timedelta(days=1, minutes=5)
    newer = datetime.now(timezone.utc) - timedelta(days=1)

    _mk_notif(db, u, wl, l, reason="tracked_price_drop", score=50, sent_at=older)
    _mk_notif(db, u, wl, l, reason="tracked_price_drop", score=90, sent_at=newer)

    p = build_weekly_digest_for_user(db, user_id=u.id, days=7)
    assert len(p["price_drops"]) == 1
    assert p["price_drops"][0]["score_v2"] == 90


def test_digest_candidates_empty(db):
    assert build_weekly_digest_candidates(db, days=7, limit=20) == []


def test_digest_candidates_counts_window_order_and_caps(db):
    u1 = _mk_user(db, 1001)
    u2 = _mk_user(db, 1002)
    wl1 = _mk_wl(db, u1, "Civic EXL Touring versão muito grande para truncar")
    wl2 = _mk_wl(db, u2, "Corolla")
    l1 = _mk_listing(db, "c1", "Honda Civic EXL 2019 Automático Muito Muito Grande")
    l2 = _mk_listing(db, "c2", "Corolla XEI")
    _mk_notif(db, u1, wl1, l1, days_ago=1, reason="match", score=91)
    _mk_notif(db, u1, wl1, l1, days_ago=2, reason="tracked_price_drop", score=85)
    _mk_notif(db, u1, wl1, l1, days_ago=31, reason="tracked_price_drop", score=50)
    _mk_notif(db, u2, wl2, l2, days_ago=1, reason="match", score=80)

    rows = build_weekly_digest_candidates(db, days=999, limit=999)
    assert len(rows) == 2
    assert rows[0]["telegram_chat_id"] == 1001
    assert rows[0]["total_sent"] == 2
    assert rows[0]["total_wishlists_with_results"] == 1
    assert rows[0]["total_price_drops"] == 1
    assert rows[0]["top_score_v2"] == 91
    assert rows[0]["latest_sent_at"] is not None
    assert rows[0]["sample_wishlist_names"]
    assert rows[0]["sample_listing_titles"]

    rows_min = build_weekly_digest_candidates(db, days=0, limit=1)
    assert len(rows_min) == 1


def test_digest_candidates_only_enabled_filter(db):
    u1 = _mk_user(db, 2001)
    u2 = _mk_user(db, 2002)
    wl1 = _mk_wl(db, u1, "A")
    wl2 = _mk_wl(db, u2, "B")
    l1 = _mk_listing(db, "e1", "A")
    l2 = _mk_listing(db, "e2", "B")
    _mk_notif(db, u1, wl1, l1, days_ago=1, reason="match", score=70)
    _mk_notif(db, u2, wl2, l2, days_ago=1, reason="match", score=80)
    set_weekly_digest_enabled(db, u2.id, True)

    all_rows = build_weekly_digest_candidates(db, days=7, limit=20, only_enabled=False)
    enabled_rows = build_weekly_digest_candidates(db, days=7, limit=20, only_enabled=True)

    assert len(all_rows) == 2
    assert len(enabled_rows) == 1
    assert enabled_rows[0]["telegram_chat_id"] == 2002
