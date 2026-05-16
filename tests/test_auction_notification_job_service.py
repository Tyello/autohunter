import types
import uuid


from app.models.app_kv import AppKV
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.auction_notification_job_service import run_auction_notification_job


def test_job_dry_run_writes_samples_without_dedupe(monkeypatch, db):
    u = User(id=uuid.uuid4(), telegram_chat_id=123)
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query="civic", is_active=True, include_auctions=True)
    db.add(w)
    db.commit()

    monkeypatch.setattr("app.services.auction_notification_job_service.list_user_eligible_auction_sources", lambda _db: {"vip_auctions"})
    monkeypatch.setattr(
        "app.services.auction_notification_job_service.build_auction_notifications_for_wishlist",
        lambda *_a, **_k: {"items": [{"chat_id": 123, "text": "x", "dedupe_key": "auction:1:vip:a", "source": "vip_auctions", "external_id": "161895", "title": "SONG PLUS", "current_bid": "91000.00", "initial_bid": None, "score": 76, "url": "https://vip/161895"}], "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 2, "skipped_missing_lot_updated_at": 3, "errors": 0, "messages": []},
    )

    import asyncio
    out = asyncio.run(run_auction_notification_job(db, bot=None, dry_run=True))
    assert out["previews"] == 1
    samples = db.query(AppKV).filter(AppKV.key == "auction_last_dry_run_samples").first()
    assert samples is not None
    assert len(samples.value.get("samples", [])) == 1
    first = samples.value["samples"][0]
    assert first["source"] == "vip_auctions"
    assert first["external_id"] == "161895"
    assert first["title"] == "SONG PLUS"
    assert first["current_bid"] == "91000.00"
    assert first["score"] == 76
    assert first["url"] == "https://vip/161895"
    assert db.query(AppKV).filter(AppKV.key.like("auction:%")).count() == 0


def test_job_dry_run_limits_samples_to_10(monkeypatch, db):
    u = User(id=uuid.uuid4(), telegram_chat_id=123)
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query="civic", is_active=True, include_auctions=True)
    db.add(w)
    db.commit()

    monkeypatch.setattr("app.services.auction_notification_job_service.list_user_eligible_auction_sources", lambda _db: {"vip_auctions"})
    monkeypatch.setattr(
        "app.services.auction_notification_job_service.build_auction_notifications_for_wishlist",
        lambda *_a, **_k: {"items": [{"chat_id": 123, "text": "x", "dedupe_key": f"auction:{i}", "title": f"title {i}"} for i in range(12)], "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 2, "skipped_missing_lot_updated_at": 3, "errors": 0, "messages": []},
    )

    import asyncio
    asyncio.run(run_auction_notification_job(db, bot=None, dry_run=True))
    samples = db.query(AppKV).filter(AppKV.key == "auction_last_dry_run_samples").first()
    assert len(samples.value.get("samples", [])) == 10


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
        lambda *_a, **_k: {"items": [{"chat_id": 123, "text": "x", "dedupe_key": "auction:1:vip:a"}], "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 2, "skipped_missing_lot_updated_at": 3, "errors": 0, "messages": []},
    )

    import asyncio
    out = asyncio.run(run_auction_notification_job(db, bot=Bot(), dry_run=False, max_per_user_per_day=1))
    assert out["sent"] == 1
    assert sent
    out2 = asyncio.run(run_auction_notification_job(db, bot=Bot(), dry_run=False, max_per_user_per_day=1))
    assert out2["skipped_daily_limit"] == 1
