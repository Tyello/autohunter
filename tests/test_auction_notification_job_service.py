import types
import uuid


from app.models.app_kv import AppKV
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.auction_notification_job_service import run_auction_notification_job


def test_job_dry_run_does_not_send_or_write_appkv(monkeypatch, db):
    u = User(id=uuid.uuid4(), telegram_chat_id=123)
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query="civic", is_active=True, include_auctions=True)
    db.add(w)
    db.commit()

    monkeypatch.setattr("app.services.auction_notification_job_service.list_user_eligible_auction_sources", lambda _db: {"vip_auctions"})
    monkeypatch.setattr(
        "app.services.auction_notification_job_service.build_auction_notifications_for_wishlist",
        lambda *_a, **_k: {"items": [{"chat_id": 123, "text": "x", "dedupe_key": "auction:1:vip:a"}], "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "errors": 0, "messages": []},
    )

    import asyncio
    out = asyncio.run(run_auction_notification_job(db, bot=None, dry_run=True))
    assert out["previews"] == 1
    assert db.query(AppKV).count() == 0


def test_job_real_sends_and_respects_daily_limit(monkeypatch, db):
    u = User(id=uuid.uuid4(), telegram_chat_id=123)
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query="civic", is_active=True, include_auctions=True)
    db.add(w)
    db.commit()

    sent = []

    class Bot:
        async def send_message(self, **kwargs):
            sent.append(kwargs)

    monkeypatch.setattr("app.services.auction_notification_job_service.list_user_eligible_auction_sources", lambda _db: {"vip_auctions"})
    monkeypatch.setattr(
        "app.services.auction_notification_job_service.build_auction_notifications_for_wishlist",
        lambda *_a, **_k: {"items": [{"chat_id": 123, "text": "x", "dedupe_key": "auction:1:vip:a"}], "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "errors": 0, "messages": []},
    )

    import asyncio
    out = asyncio.run(run_auction_notification_job(db, bot=Bot(), dry_run=False, max_per_user_per_day=1))
    assert out["sent"] == 1
    assert sent
    out2 = asyncio.run(run_auction_notification_job(db, bot=Bot(), dry_run=False, max_per_user_per_day=1))
    assert out2["skipped_daily_limit"] == 1
