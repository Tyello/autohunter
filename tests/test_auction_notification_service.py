import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.app_kv import AppKV
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.auction_lot_service import upsert_lot
from app.services.auction_notification_service import build_auction_notifications_for_wishlist, send_auction_notifications_for_wishlist


def test_wishlist_not_found(db):
    res = build_auction_notifications_for_wishlist(db, str(uuid.uuid4()))
    assert res["errors"] == 1


def test_include_auctions_block_and_force(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=111, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic", is_active=True, include_auctions=False)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "x1", "title": "civic", "status": "open", "url": "https://lot/1"})
    db.commit()
    assert build_auction_notifications_for_wishlist(db, w.id)["errors"] == 1
    assert build_auction_notifications_for_wishlist(db, w.id, force=True)["errors"] == 0


def test_missing_chat_no_send(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=0, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic", is_active=True, include_auctions=True)
    db.add(w); db.commit()
    res = build_auction_notifications_for_wishlist(db, w.id)
    assert res["skipped_missing_chat_id"] == 1


def test_send_and_dedupe_and_filters(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=222, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "a1", "title": "Honda Civic 2015", "year": 2015, "status": "ended", "url": "https://lot/a1"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "a2", "title": "Honda Civic 2015", "year": 2015, "status": "open", "url": None})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "a3", "title": "Honda Civic 2015", "year": 2015, "status": "open", "url": "https://lot/a3"})
    db.commit()

    sent_msgs = []
    class Bot:
        async def send_message(self, **kwargs):
            sent_msgs.append(kwargs)

    import asyncio
    res = asyncio.run(send_auction_notifications_for_wishlist(db, Bot(), w.id, limit=5))
    assert res["sent"] == 1
    assert sent_msgs and "Preview" not in sent_msgs[0]["text"]

    res2 = asyncio.run(send_auction_notifications_for_wishlist(db, Bot(), w.id, limit=1))
    assert res2["skipped_duplicate"] >= 1

    forced = build_auction_notifications_for_wishlist(db, w.id, force=True, limit=4)
    assert forced["sent"] <= 3
    assert any(isinstance(x, AppKV) for x in db.query(AppKV).all())


def test_build_dry_run_does_not_send_or_persist(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=444, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "dry1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "url": "https://lot/dry1"})
    db.commit()

    res = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert res["sent"] == 1
    assert len(res.get("items", [])) == 1
    assert db.query(AppKV).count() == 0


def test_no_match(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=333, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="termo inexistente", is_active=True, include_auctions=True)
    db.add(w); db.commit()
    res = build_auction_notifications_for_wishlist(db, w.id)
    assert res["skipped_no_match"] >= 1


def test_notify_source_filter_with_eligible_sources(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=555, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "mega_auctions", "external_id": "m1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "url": "https://lot/m1"})
    db.commit()
    blocked = build_auction_notifications_for_wishlist(db, w.id, source="mega_auctions", eligible_sources={"vip_auctions"})
    assert blocked["sent"] == 0
    allowed = build_auction_notifications_for_wishlist(db, w.id, source="mega_auctions", eligible_sources=None)
    assert allowed["sent"] >= 0
