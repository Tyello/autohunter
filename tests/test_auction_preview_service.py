import uuid

from app.services.auction_lot_service import upsert_lot
from app.services.auction_preview_service import (
    build_auction_alert_previews_for_enabled_wishlists,
    build_auction_alert_previews_for_wishlist,
)
from app.models.user import User
from app.models.wishlist import Wishlist


def test_preview_service_respects_include_auctions(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=1001, username="x")
    db.add(u)
    db.flush()
    w_on = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    w_off = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=False)
    db.add_all([w_on, w_off])
    upsert_lot(db, {"source": "vip_auctions", "external_id": "p1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "current_bid": 90000, "url": "https://vip/l1"})
    db.commit()

    matches = build_auction_alert_previews_for_enabled_wishlists(db, limit=5)
    assert matches
    assert all(m.wishlist_id == str(w_on.id) for m in matches)


def test_preview_service_wishlist_force_and_block(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=1002, username="y")
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=False)
    db.add(w)
    upsert_lot(db, {"source": "vip_auctions", "external_id": "p2", "title": "Honda Civic 2015", "year": 2015, "status": "open", "current_bid": 90000, "url": "https://vip/l2"})
    db.commit()

    blocked = build_auction_alert_previews_for_wishlist(db, str(w.id), force=False)
    assert "--force" in (blocked.warning or "")

    forced = build_auction_alert_previews_for_wishlist(db, str(w.id), force=True)
    assert forced.warning is None
    assert forced.matches
