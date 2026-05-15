from decimal import Decimal
import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.notification import Notification
from app.services.auction_lot_service import upsert_lot
from app.services.auction_matching_service import match_auction_lots_for_all_wishlists, match_auction_lots_for_wishlist


def _mk_wishlist(db, query: str):
    u = User(id=uuid.uuid4(), telegram_chat_id=70001, username="admin")
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query=query, is_active=True)
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def test_match_by_title_and_year_and_source_filter(db):
    w = _mk_wishlist(db, "civic si 2015")
    upsert_lot(db, {"source": "vip_auctions", "external_id": "a1", "title": "Honda Civic Si 2015", "year": 2015, "current_bid": Decimal("35000") ,"status": "open"})
    upsert_lot(db, {"source": "copart_auctions", "external_id": "a2", "title": "Honda Civic LX 2014", "year": 2014, "status": "open"})
    db.commit()

    matches = match_auction_lots_for_wishlist(db, w, limit=10)
    assert matches
    assert matches[0].source == "vip_auctions"
    assert matches[0].year == 2015
    assert matches[0].risk_label == "auction"

    vip_only = match_auction_lots_for_wishlist(db, w, source="vip_auctions", limit=10)
    assert vip_only
    assert all(m.source == "vip_auctions" for m in vip_only)


def test_filter_by_wishlist_and_no_notifications_created(db):
    w1 = _mk_wishlist(db, "corolla 2020")
    u2 = User(id=uuid.uuid4(), telegram_chat_id=70002, username="admin2")
    db.add(u2)
    db.flush()
    w2 = Wishlist(user_id=u2.id, query="civic 2015", is_active=True)
    db.add(w2)
    db.commit()
    db.refresh(w2)
    upsert_lot(db, {"source": "vip_auctions", "external_id": "x1", "title": "Toyota Corolla 2020", "year": 2020, "status": "open"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "x2", "title": "Honda Civic 2015", "year": 2015, "status": "open"})
    db.commit()

    all_matches = match_auction_lots_for_all_wishlists(db, source="vip_auctions", limit_per_wishlist=5)
    assert str(w1.id) in all_matches
    assert str(w2.id) in all_matches

    only_w1 = match_auction_lots_for_wishlist(db, w1, source="vip_auctions", limit=5)
    assert only_w1
    assert any("corolla" in (m.title or "").lower() for m in only_w1)

    assert db.query(Notification).count() == 0


def test_no_matches_returns_empty(db):
    w = _mk_wishlist(db, "porsche 911")
    upsert_lot(db, {"source": "vip_auctions", "external_id": "z1", "title": "Uno Mille", "year": 2010, "status": "open"})
    db.commit()
    matches = match_auction_lots_for_wishlist(db, w, limit=5)
    assert matches == []
