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
        lambda *_a, **_k: {"items": [{"chat_id": 123, "text": "x", "dedupe_key": "auction:1:vip:a", "source": "vip_auctions", "source_label": "VIP Leilões", "external_id": "161895", "title": "SONG PLUS", "current_bid": "91000.00", "initial_bid": None, "score": 76, "url": "https://vip/161895", "button_label": "🔗 Ver leilão", "year": 2019, "mileage_km": 50500, "total_bids": 7, "auction_end_at": datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc), "location": "São Paulo/SP", "item_type": "car"}], "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 2, "skipped_missing_lot_updated_at": 3, "errors": 0, "messages": []},
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
    assert first["button_label"] == "🔗 Ver leilão"
    assert first["year"] == 2019
    assert first["mileage_km"] == 50500
    assert first["total_bids"] == 7
    assert first["auction_end_at"] == "2026-05-18T15:00:00+00:00"
    assert first["location"] == "São Paulo/SP"
    assert first["item_type"] == "car"
    assert first["source_label"] == "VIP Leilões"
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
        lambda *_a, **_k: {"items": [{"chat_id": 123, "text": "x", "dedupe_key": "auction:1:vip:a", "reply_markup": {"inline_keyboard": []}}], "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 2, "skipped_missing_lot_updated_at": 3, "errors": 0, "messages": []},
    )

    import asyncio
    out = asyncio.run(run_auction_notification_job(db, bot=Bot(), dry_run=False, max_per_user_per_day=1))
    assert out["sent"] == 1
    assert sent
    assert "reply_markup" in sent[0]
    out2 = asyncio.run(run_auction_notification_job(db, bot=Bot(), dry_run=False, max_per_user_per_day=1))
    assert out2["skipped_daily_limit"] == 1


def test_job_real_dedupe_blocks_second_send(monkeypatch, db):
    u = User(id=uuid.uuid4(), telegram_chat_id=123)
    db.add(u)
    db.flush()
    w = Wishlist(id=uuid.uuid4(), user_id=u.id, query="touareg", is_active=True, include_auctions=True)
    db.add(w)
    db.commit()
    sent = []

    class Bot:
        async def send_message(self, **kwargs):
            sent.append(kwargs)

    dedupe_key = f"auction:{w.id}:vip_auctions:lot-1"

    def _fake_build(_db, wishlist_id, **_kwargs):
        exists = _db.query(AppKV).filter(AppKV.key == dedupe_key).first()
        if exists:
            return {
                "items": [],
                "skipped_duplicate": 1,
                "skipped_no_match": 0,
                "skipped_missing_chat_id": 0,
                "skipped_score_below_min": 0,
                "skipped_stale_lot": 0,
                "skipped_missing_lot_updated_at": 0,
                "skipped_item_type_not_allowed": 0,
                "errors": 0,
                "messages": [],
            }
        return {
            "items": [{"chat_id": 123, "text": "x", "dedupe_key": dedupe_key}],
            "skipped_duplicate": 0,
            "skipped_no_match": 0,
            "skipped_missing_chat_id": 0,
            "skipped_score_below_min": 0,
            "skipped_stale_lot": 0,
            "skipped_missing_lot_updated_at": 0,
            "skipped_item_type_not_allowed": 0,
            "errors": 0,
            "messages": [],
        }

    monkeypatch.setattr("app.services.auction_notification_job_service.list_user_eligible_auction_sources", lambda _db: {"vip_auctions"})
    monkeypatch.setattr("app.services.auction_notification_job_service.build_auction_notifications_for_wishlist", _fake_build)
    import asyncio
    first = asyncio.run(run_auction_notification_job(db, bot=Bot(), dry_run=False, max_per_user_per_day=5))
    second = asyncio.run(run_auction_notification_job(db, bot=Bot(), dry_run=False, max_per_user_per_day=5))
    assert first["sent"] == 1
    assert second["sent"] == 0
    assert second["skipped_duplicate"] == 1
    assert len(sent) == 1


from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.services.auction_notification_job_service import _json_safe


def test_json_safe_converts_nested_types():
    payload = {
        "decimal": Decimal("8500.00"),
        "datetime": datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        "date": date(2026, 5, 17),
        "uuid": uuid4(),
        "nested": [{"v": Decimal("1.23")}, (Decimal("2.34"),)],
        "int": 1,
        "bool": True,
        "none": None,
    }

    out = _json_safe(payload)
    assert out["decimal"] == "8500.00"
    assert out["datetime"] == "2026-05-17T12:00:00+00:00"
    assert out["date"] == "2026-05-17"
    assert isinstance(out["uuid"], str)
    assert out["nested"][0]["v"] == "1.23"
    assert out["nested"][1][0] == "2.34"


def test_job_dry_run_persists_rejections_with_decimal_current_bid(monkeypatch, db):
    u = User(id=uuid.uuid4(), telegram_chat_id=123)
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query="civic", is_active=True, include_auctions=True)
    db.add(w)
    db.commit()

    monkeypatch.setattr("app.services.auction_notification_job_service.list_user_eligible_auction_sources", lambda _db: {"vip_auctions"})
    monkeypatch.setattr(
        "app.services.auction_notification_job_service.build_auction_notifications_for_wishlist",
        lambda *_a, **_k: {
            "items": [],
            "rejections": [{"reason": "score_below_min", "current_bid": Decimal("8500.00"), "updated_at": datetime(2026, 5, 17, tzinfo=timezone.utc)}],
            "skipped_duplicate": 0, "skipped_no_match": 1, "skipped_missing_chat_id": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 0, "skipped_missing_lot_updated_at": 0, "errors": 0, "messages": []
        },
    )

    import asyncio
    out = asyncio.run(run_auction_notification_job(db, bot=None, dry_run=True))
    assert out["errors"] == 0
    row = db.query(AppKV).filter(AppKV.key == "auction_last_dry_run_samples").first()
    assert row is not None
    assert row.value["rejections"][0]["current_bid"] == "8500.00"
    assert row.value["rejections"][0]["updated_at"] == "2026-05-17T00:00:00+00:00"


def test_job_dry_run_counts_item_type_not_allowed(monkeypatch, db):
    u = User(id=uuid.uuid4(), telegram_chat_id=123)
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query="song pro", is_active=True, include_auctions=True)
    db.add(w)
    db.commit()

    monkeypatch.setattr("app.services.auction_notification_job_service.list_user_eligible_auction_sources", lambda _db: {"vip_auctions"})
    monkeypatch.setattr(
        "app.services.auction_notification_job_service.build_auction_notifications_for_wishlist",
        lambda *_a, **_k: {"items": [], "skipped_duplicate": 0, "skipped_no_match": 1, "skipped_missing_chat_id": 0, "skipped_score_below_min": 0, "skipped_stale_lot": 0, "skipped_missing_lot_updated_at": 0, "skipped_item_type_not_allowed": 1, "errors": 0, "messages": [], "rejections": [{"reason": "item_type_not_allowed", "title": "F700 GS"}]},
    )

    import asyncio
    out = asyncio.run(run_auction_notification_job(db, bot=None, dry_run=True))
    assert out["skipped_item_type_not_allowed"] == 1
    assert out["skipped_score_below_min"] == 0
    assert out["previews"] == 0
